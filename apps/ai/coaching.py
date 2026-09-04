from __future__ import annotations

import html
import json
import re
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Max
from django.utils import timezone

from apps.prds.models import (
    Prd,
    PrdAnswer,
    PrdChangeHistory,
    PrdQuestion,
    PrdSection,
)

from .exceptions import AiOutputValidationError
from .models import (
    AiActionType,
    AiCoachChatLog,
    AiCoachConversation,
    AiCoachMessage,
    AiConversationMessageRole,
    AiFeatureType,
    AiJob,
    AiJobStatus,
)
from .services import AiJobService


class AiDraftVersionConflict(Exception):
    def __init__(self, question: PrdQuestion):
        super().__init__("The question changed after the draft was requested.")
        self.question = question


def escape_user_message(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError({"message": "메시지는 문자열이어야 합니다."})
    normalized = value.strip()
    if not normalized:
        raise ValidationError({"message": "메시지를 입력해 주세요."})
    if len(normalized) > settings.AI_CHAT_MESSAGE_MAX_LENGTH:
        raise ValidationError(
            {"message": f"메시지는 {settings.AI_CHAT_MESSAGE_MAX_LENGTH}자 이하여야 합니다."}
        )
    return html.escape(normalized, quote=False)


def model_text(value: str) -> str:
    """저장·표시용 이스케이프를 풀어 모델에 보낼 원문으로 되돌린다.

    저장할 때는 화면 안전을 위해 &lt; 같은 형태로 두지만, 그대로 모델에 보내면
    프롬프트에 실체 없는 기호가 섞여 답변 품질이 떨어진다.
    """
    return html.unescape(value or "")


def sanitize_ai_markdown(value: Any) -> str:
    if not isinstance(value, str):
        raise AiOutputValidationError("AI response must be a string.")
    normalized = value.strip()
    if not normalized:
        raise AiOutputValidationError("AI response must not be blank.")
    if len(normalized) > settings.AI_RESPONSE_MAX_LENGTH:
        raise AiOutputValidationError("AI response exceeded the configured length limit.")
    normalized = "".join(
        character for character in normalized if character in "\n\r\t" or ord(character) >= 32
    )
    normalized = re.sub(
        r"\]\(\s*(?:javascript|data):[^)]*\)",
        "](#)",
        normalized,
        flags=re.IGNORECASE,
    )
    return html.escape(normalized, quote=False)


class PrdAiContextBuilder:
    def build(self, *, prd: Prd, section: PrdSection | None) -> dict[str, Any]:
        sections = PrdSection.objects.filter(prd=prd, is_deleted=False).order_by("position", "id")
        if section is not None:
            sections = sections.filter(pk=section.pk)

        context: dict[str, Any] = {
            "prd": {
                "id": prd.pk,
                "title": prd.title,
                "description": prd.description,
                "scope_section_id": section.pk if section else None,
            },
            "sections": [],
            "truncated": False,
        }
        for current_section in sections:
            section_data = {
                "id": current_section.pk,
                "title": current_section.title,
                "guide": current_section.guide,
                "questions": [],
            }
            candidate = {**context, "sections": [*context["sections"], section_data]}
            if self._size(candidate) > settings.AI_CONTEXT_MAX_CHARS:
                context["truncated"] = True
                break
            context["sections"].append(section_data)
            for question in current_section.questions.filter(
                is_deleted=False,
                is_held=False,
            ).order_by(
                "position", "id"
            ):
                try:
                    answer = question.answer.content
                except ObjectDoesNotExist:
                    answer = ""
                question_data = {
                    "id": question.pk,
                    "version": question.version,
                    "prompt": question.prompt,
                    "answer": answer,
                }
                candidate = {
                    **context,
                    "sections": [
                        *context["sections"][:-1],
                        {
                            **section_data,
                            "questions": [*section_data["questions"], question_data],
                        },
                    ],
                }
                if self._size(candidate) > settings.AI_CONTEXT_MAX_CHARS:
                    context["truncated"] = True
                    break
                section_data["questions"].append(question_data)
        if self._size(context) > settings.AI_CONTEXT_MAX_CHARS:
            raise ValidationError(
                {"context": "PRD 제목과 설명이 AI Context 최대 크기를 초과했습니다."}
            )
        return context

    @staticmethod
    def _size(value) -> int:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


class AiCoachConversationService:
    TTL = timedelta(days=30)

    @transaction.atomic
    def get_or_create_locked(
        self,
        *,
        prd: Prd,
        section: PrdSection | None,
        user_id: int,
    ) -> AiCoachConversation:
        lookup = {"prd": prd, "section": section, "user_id": user_id}
        conversation = AiCoachConversation.objects.filter(**lookup).first()
        if conversation and conversation.expires_at <= timezone.now():
            conversation.delete()
            conversation = None
        if conversation is None:
            try:
                with transaction.atomic():
                    conversation = AiCoachConversation.objects.create(
                        **lookup,
                        expires_at=timezone.now() + self.TTL,
                    )
            except IntegrityError:
                conversation = AiCoachConversation.objects.get(**lookup)
        return AiCoachConversation.objects.select_for_update().get(pk=conversation.pk)

    def get(self, *, prd, section, user_id):
        conversation = AiCoachConversation.objects.filter(
            prd=prd,
            section=section,
            user_id=user_id,
            expires_at__gt=timezone.now(),
        ).first()
        return conversation

    @transaction.atomic
    def request_chat(
        self,
        *,
        prd: Prd,
        section: PrdSection | None,
        user_id: int,
        message: str,
        idempotency_key: str,
    ) -> tuple[AiJob, bool]:
        existing = AiJob.objects.filter(
            prd=prd,
            user_id=user_id,
            feature_type=AiFeatureType.COACHING,
            idempotency_key=idempotency_key.strip(),
        ).first()
        if existing:
            return existing, False

        conversation = self.get_or_create_locked(
            prd=prd,
            section=section,
            user_id=user_id,
        )
        existing = AiJob.objects.filter(
            prd=prd,
            user_id=user_id,
            feature_type=AiFeatureType.COACHING,
            idempotency_key=idempotency_key.strip(),
        ).first()
        if existing:
            return existing, False

        safe_message = escape_user_message(message)
        history = self._recent_complete_turns(conversation)
        sequence = self._next_sequence(conversation)
        user_message = AiCoachMessage.objects.create(
            conversation=conversation,
            sequence=sequence,
            role=AiConversationMessageRole.USER,
            content=safe_message,
        )
        context = PrdAiContextBuilder().build(prd=prd, section=section)
        job, created = AiJobService().enqueue(
            prd=prd,
            user_id=user_id,
            feature_type=AiFeatureType.COACHING,
            action_type=AiActionType.CHAT,
            input_data={
                "kind": "coach_chat",
                "conversation_id": conversation.pk,
                "user_message_id": user_message.pk,
                # 저장은 이스케이프된 형태로, 모델에는 원문으로 보낸다.
                "current_message": model_text(safe_message),
                "recent_turns": history,
                # 사용자가 물린 제안을 다시 내지 않도록 근거를 함께 넘긴다.
                "declined_proposals": self._declined_proposals(conversation),
                "prd_context": context,
            },
            idempotency_key=idempotency_key,
        )
        user_message.job = job
        user_message.save(update_fields=["job"])
        conversation.expires_at = timezone.now() + self.TTL
        conversation.save(update_fields=["expires_at", "updated_at"])
        return job, created

    @staticmethod
    def _next_sequence(conversation) -> int:
        current = conversation.messages.aggregate(value=Max("sequence"))["value"] or 0
        return current + 1

    @staticmethod
    def _declined_proposals(conversation) -> list[dict[str, Any]]:
        """이 대화에서 사용자가 거절한 제안 목록.

        최근 대화 텍스트에는 승인·거절 여부가 남지 않으므로 따로 모아 전달한다.
        """
        jobs = (
            AiJob.objects.filter(
                coach_messages__conversation=conversation,
                feature_type=AiFeatureType.COACHING,
                action_type=AiActionType.CHAT,
                output_data__declined_at__isnull=False,
            )
            .order_by("-created_at")
            .distinct()[: settings.AI_CHAT_RECENT_TURNS]
        )
        declined = []
        for job in jobs:
            proposal = (job.output_data or {}).get("proposal") or {}
            if not proposal:
                continue
            declined.append(
                {
                    "question_id": proposal.get("question_id"),
                    "content": model_text(proposal.get("content", "")),
                    "reason": model_text(proposal.get("reason", "")),
                }
            )
        return declined

    @staticmethod
    def _recent_complete_turns(conversation) -> list[dict[str, str]]:
        assistants = list(
            conversation.messages.filter(
                role=AiConversationMessageRole.ASSISTANT,
                job__isnull=False,
            )
            .select_related("job")
            .order_by("-sequence")[: settings.AI_CHAT_RECENT_TURNS]
        )
        turns = []
        for assistant in reversed(assistants):
            user_message = conversation.messages.filter(
                job=assistant.job,
                role=AiConversationMessageRole.USER,
            ).first()
            if user_message:
                # 지난 턴도 모델에는 원문으로 전달한다.
                turns.append(
                    {
                        "user": model_text(user_message.content),
                        "assistant": model_text(assistant.content),
                    }
                )
        return turns


class AiChatProposalService:
    """코치 제안을 사용자가 승인했을 때만 PRD 답변에 반영한다."""

    @transaction.atomic
    def apply(self, *, job: AiJob, question_version: int, content: str, user_id: int) -> PrdAnswer:
        job = AiJob.objects.select_for_update().select_related("prd").get(pk=job.pk)
        if (
            job.user_id != user_id
            or job.feature_type != AiFeatureType.COACHING
            or job.action_type != AiActionType.CHAT
            or job.status != AiJobStatus.SUCCEEDED
        ):
            raise ValidationError({"job": "반영할 수 있는 코치 제안이 아닙니다."})
        output = job.output_data or {}
        proposal = output.get("proposal")
        if not isinstance(proposal, dict):
            raise ValidationError({"job": "이 답변에는 반영할 제안이 없습니다."})
        if output.get("applied_at"):
            # 버전 검사에도 걸리지만, 여기서 막아야 이유가 분명한 메시지가 나간다.
            raise ValidationError({"job": "이미 반영한 제안입니다."})
        if output.get("declined_at"):
            raise ValidationError({"job": "이미 거절한 제안입니다."})
        return _apply_answer(
            prd=job.prd,
            question_id=proposal.get("question_id"),
            generated_version=proposal.get("question_version"),
            question_version=question_version,
            content=content,
            user_id=user_id,
            event_type="ai_chat_proposal_applied",
            job=job,
        )

    @transaction.atomic
    def decline(self, *, job: AiJob, user_id: int) -> AiJob:
        """거절도 서버에 남긴다.

        남기지 않으면 거절과 아직 고르지 않은 상태를 구분할 수 없어
        새로고침할 때 제안이 되살아나고, 다음 요청에서 같은 제안을 막을 근거도 없다.
        """
        job = AiJob.objects.select_for_update().get(pk=job.pk)
        if (
            job.user_id != user_id
            or job.feature_type != AiFeatureType.COACHING
            or job.action_type != AiActionType.CHAT
            or job.status != AiJobStatus.SUCCEEDED
        ):
            raise ValidationError({"job": "거절할 수 있는 코치 제안이 아닙니다."})
        output = job.output_data or {}
        if not isinstance(output.get("proposal"), dict):
            raise ValidationError({"job": "이 답변에는 거절할 제안이 없습니다."})
        if output.get("applied_at"):
            raise ValidationError({"job": "이미 반영한 제안입니다."})
        if not output.get("declined_at"):
            job.output_data = {**output, "declined_at": timezone.now().isoformat()}
            job.save(update_fields=["output_data", "updated_at"])
        return job


def _apply_answer(
    *,
    prd,
    question_id,
    generated_version,
    question_version,
    content,
    user_id,
    event_type,
    job,
):
    """초안과 코치 제안이 공유하는 반영 절차.

    제안이 만들어진 뒤 질문이 바뀌었으면 덮어쓰지 않고 409로 되돌린다.
    """
    try:
        question = PrdQuestion.objects.select_for_update().get(
            pk=question_id,
            section__prd=prd,
            section__is_deleted=False,
            is_deleted=False,
            is_held=False,
        )
    except PrdQuestion.DoesNotExist as exc:
        raise ValidationError({"question_id": "질문을 찾을 수 없습니다."}) from exc
    if question.version != generated_version or question.version != question_version:
        raise AiDraftVersionConflict(question)
    if not isinstance(content, str) or not content.strip():
        raise ValidationError({"content": "반영할 답변을 입력해 주세요."})
    content = content.strip()
    if len(content) > settings.AI_DRAFT_MAX_LENGTH:
        raise ValidationError(
            {"content": f"답변은 {settings.AI_DRAFT_MAX_LENGTH}자 이하여야 합니다."}
        )
    try:
        previous = question.answer.content
    except ObjectDoesNotExist:
        previous = ""
    answer, _ = PrdAnswer.objects.update_or_create(
        question=question,
        defaults={"content": content, "updated_by_user_id": user_id},
    )
    question.version += 1
    question.save(update_fields=["version", "updated_at"])
    now = timezone.now()
    Prd.objects.filter(pk=prd.pk).update(version=F("version") + 1, updated_at=now)
    PrdChangeHistory.objects.create(
        prd=prd,
        actor_user_id=user_id,
        event_type=event_type,
        before_data={"question_id": question.pk, "content": previous},
        after_data={
            "question_id": question.pk,
            "content": content,
            "question_version": question.version,
        },
    )
    job.output_data = {
        **(job.output_data or {}),
        "applied_at": now.isoformat(),
        "applied_question_version": question.version,
    }
    job.save(update_fields=["output_data", "updated_at"])
    return answer


class AiDraftService:
    @transaction.atomic
    def request(
        self,
        *,
        prd: Prd,
        question: PrdQuestion,
        user_id: int,
        idempotency_key: str,
    ) -> tuple[AiJob, bool]:
        context = PrdAiContextBuilder().build(prd=prd, section=question.section)
        return AiJobService().enqueue(
            prd=prd,
            user_id=user_id,
            feature_type=AiFeatureType.COACHING,
            action_type=AiActionType.DRAFT,
            input_data={
                "kind": "question_draft",
                "question_id": question.pk,
                "question_version": question.version,
                "prd_context": context,
            },
            idempotency_key=idempotency_key,
        )

    @transaction.atomic
    def apply(
        self,
        *,
        job: AiJob,
        question_version: int,
        content: str,
        user_id: int,
    ) -> PrdAnswer:
        job = AiJob.objects.select_for_update().select_related("prd").get(pk=job.pk)
        if (
            job.user_id != user_id
            or job.feature_type != AiFeatureType.COACHING
            or job.action_type != AiActionType.DRAFT
            or job.status != AiJobStatus.SUCCEEDED
        ):
            raise ValidationError({"job": "반영할 수 있는 질문 초안 작업이 아닙니다."})
        return _apply_answer(
            prd=job.prd,
            question_id=job.input_data.get("question_id"),
            generated_version=job.input_data.get("question_version"),
            question_version=question_version,
            content=content,
            user_id=user_id,
            event_type="ai_draft_applied",
            job=job,
        )


class AiResultProcessor:
    """Persists feature-specific results after common schema/reference validation."""

    def process(self, *, job: AiJob, output: dict[str, Any]) -> dict[str, Any]:
        if job.feature_type != AiFeatureType.COACHING:
            return output
        if job.action_type == AiActionType.CHAT:
            return self._process_chat(job=job, output=output)
        if job.action_type == AiActionType.DRAFT:
            return self._process_draft(job=job, output=output)
        return output

    def _process_chat(self, *, job, output):
        safe_message = sanitize_ai_markdown(output.get("message"))
        proposal = self._build_proposal(job=job, output=output)
        conversation_id = job.input_data.get("conversation_id")
        try:
            conversation = AiCoachConversation.objects.select_for_update().get(
                pk=conversation_id,
                prd=job.prd,
                user_id=job.user_id,
            )
        except AiCoachConversation.DoesNotExist as exc:
            raise AiOutputValidationError("AI conversation no longer exists.") from exc
        if not conversation.messages.filter(
            job=job,
            role=AiConversationMessageRole.ASSISTANT,
        ).exists():
            AiCoachMessage.objects.create(
                conversation=conversation,
                job=job,
                sequence=AiCoachConversationService._next_sequence(conversation),
                role=AiConversationMessageRole.ASSISTANT,
                content=safe_message,
            )
            user_message = conversation.messages.filter(
                job=job,
                role=AiConversationMessageRole.USER,
            ).first()
            AiCoachChatLog.objects.create(
                prd=job.prd,
                user_id=job.user_id,
                prompt=user_message.content if user_message else "",
                response=safe_message,
            )
        conversation.expires_at = timezone.now() + AiCoachConversationService.TTL
        conversation.save(update_fields=["expires_at", "updated_at"])
        result = {"message": safe_message}
        if proposal is not None:
            result["proposal"] = proposal
        return result

    @staticmethod
    def _build_proposal(*, job, output):
        """코치가 특정 질문의 답변 수정을 제안했을 때만 만들어진다.

        제안은 저장하지 않는다. 사용자가 화면에서 승인해야 PRD에 반영된다.
        """
        raw = output.get("proposal")
        if not isinstance(raw, dict):
            return None
        question_id = raw.get("question_id")
        if isinstance(question_id, bool) or not isinstance(question_id, int):
            raise AiOutputValidationError("AI proposal question_id must be an integer.")
        try:
            question = PrdQuestion.objects.select_related("section").get(
                pk=question_id,
                section__prd=job.prd,
                section__is_deleted=False,
                is_deleted=False,
                is_held=False,
            )
        except PrdQuestion.DoesNotExist as exc:
            raise AiOutputValidationError("AI proposal points at another PRD question.") from exc
        content = sanitize_ai_markdown(raw.get("content"))
        if len(content) > settings.AI_DRAFT_MAX_LENGTH:
            raise AiOutputValidationError("AI proposal exceeded the draft length limit.")
        return {
            "question_id": question.pk,
            "question_version": question.version,
            "question_prompt": question.prompt,
            "section_id": question.section_id,
            "section_title": question.section.title,
            "content": content,
            "reason": sanitize_ai_markdown(raw["reason"]) if raw.get("reason") else "",
        }

    @staticmethod
    def _process_draft(*, job, output):
        question_id = job.input_data.get("question_id")
        output_question_id = output.get("question_id", question_id)
        if output_question_id != question_id:
            raise AiOutputValidationError("AI draft returned another question identifier.")
        return {
            "question_id": question_id,
            "question_version": job.input_data.get("question_version"),
            "draft": sanitize_ai_markdown(output.get("draft")),
        }


def delete_expired_conversations() -> int:
    expired_ids = list(
        AiCoachConversation.objects.filter(expires_at__lte=timezone.now())
        .order_by("expires_at")
        .values_list("pk", flat=True)[: settings.AI_TTL_DELETE_BATCH_SIZE]
    )
    if not expired_ids:
        return 0
    deleted, _ = AiCoachConversation.objects.filter(pk__in=expired_ids).delete()
    return deleted


def delete_expired_chat_history() -> int:
    """대화 열람 이력도 대화와 같은 30일 뒤에 지운다.

    이 표는 화면이 아니라 PRD 상세의 ai-chats 조회에 쓰이는데,
    같이 지우지 않으면 대화창에서 사라진 뒤에도 계속 조회된다.
    """
    cutoff = timezone.now() - AiCoachConversationService.TTL
    expired_ids = list(
        AiCoachChatLog.objects.filter(created_at__lte=cutoff)
        .order_by("created_at", "id")
        .values_list("pk", flat=True)[: settings.AI_TTL_DELETE_BATCH_SIZE]
    )
    if not expired_ids:
        return 0
    deleted, _ = AiCoachChatLog.objects.filter(pk__in=expired_ids).delete()
    return deleted
