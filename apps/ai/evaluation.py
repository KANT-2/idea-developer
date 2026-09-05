from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.prds.models import Prd, PrdQuestion

from .coaching import PrdAiContextBuilder, sanitize_ai_markdown
from .exceptions import AiOutputValidationError
from .models import (
    AiActionType,
    AiFeatureType,
    AiJob,
    AiJobStatus,
    AiUsageLog,
    AiUsageStatus,
)
from .services import AiJobService

EVALUATION_PERSONAS = {
    "pm": {
        "label": "PM 관점",
        "focus": (
            "비즈니스 타당성, 이 기능이 지금 필요한 이유, 성공 지표가 실제로 무엇을 "
            "측정하는지, 우선순위 판단의 근거, 사용자와 팀에 미치는 영향을 중심으로 "
            "본다. 구현 방법이나 기술적 세부사항은 낮은 비중으로 다룬다. 이미 채워진 "
            "내용에 대해서는 다음 질문을 스스로 던지며 검토한다: 제시된 목표 수치나 "
            "기준이 왜 그 값이어야 하는지 근거가 있는가? 이 타겟을 먼저 선택한 이유가 "
            "추측이 아니라 실제 근거에 기반하는가? 이 지표가 오르면 정말 문제가 "
            "해결됐다고 말할 수 있는가, 아니면 지표와 문제 사이에 비약이 있는가?"
        ),
    },
    "engineering": {
        "label": "엔지니어링 관점",
        "focus": (
            "구현 가능성, 데이터 모델과 연동 관계의 누락, 예외 상황 처리, 확장성과 "
            "유지보수 비용을 중심으로 본다. 사업적 타당성이나 시장성은 낮은 비중으로 "
            "다룬다. 이미 채워진 내용에 대해서는 다음 질문을 스스로 던지며 검토한다: "
            "이 기능이 실패하거나 예외 상황이 생기면 어떻게 복구하는지 답변에 나와 "
            "있는가? 여기서 말하는 데이터는 어디서 오고 언제까지 보관·삭제되는지 "
            "명시돼 있는가? 지금 적힌 범위만으로 실제 구현 착수가 가능한가, 아니면 "
            "추가로 확인해야 할 전제가 숨어 있는가?"
        ),
    },
    "investor": {
        "label": "투자자 관점",
        "focus": (
            "이 제품/기능이 왜 지금 우선순위인지, 경쟁 대안 대비 차별성이 설득력 "
            "있는지, 핵심 가설이 검증 가능한 방식으로 설계되어 있는지를 중심으로 "
            "본다. 세부 UX나 데이터 모델 이슈는 낮은 비중으로 다룬다. 이미 채워진 "
            "내용에 대해서는 다음 질문을 스스로 던지며 검토한다: 여기 적힌 차별점을 "
            "경쟁사가 단기간에 따라 할 수 없는 이유가 답변에 나와 있는가? 이 가설이 "
            "틀렸다는 걸 가장 빨리, 가장 싸게 확인할 방법이 제시돼 있는가? 지금 "
            "범위가 우선순위인 이유가 추측이 아니라 근거에 기반하는가?"
        ),
    },
}


class PrdEvaluationService:
    def request(
        self,
        *,
        prd: Prd,
        user_id: int,
        persona: Any,
        idempotency_key: str,
    ) -> tuple[AiJob, bool]:
        if persona not in EVALUATION_PERSONAS:
            raise ValidationError({"persona": "지원하는 진단 관점을 선택해 주세요."})
        context = PrdAiContextBuilder().build(prd=prd, section=None)
        if not context["sections"]:
            raise ValidationError({"prd": "진단할 PRD 섹션이 없습니다."})
        versions = {
            str(question["id"]): question["version"]
            for section in context["sections"]
            for question in section["questions"]
        }
        demo_cache_enabled = bool(
            settings.AI_EVALUATION_DEMO_CACHE and not settings.GEMINI_API_KEY.strip()
        )
        if demo_cache_enabled:
            cached = self._current_demo_job(
                prd=prd,
                user_id=user_id,
                persona=persona,
                question_versions=versions,
            )
            if cached:
                return cached, False

        job, created = AiJobService().enqueue(
            prd=prd,
            user_id=user_id,
            feature_type=AiFeatureType.PRD_EVALUATION,
            action_type=AiActionType.EVALUATION,
            input_data={
                "kind": "prd_evaluation",
                "persona": persona,
                "persona_label": EVALUATION_PERSONAS[persona]["label"],
                "evaluation_focus": EVALUATION_PERSONAS[persona]["focus"],
                "question_versions": versions,
                "context": context,
            },
            idempotency_key=idempotency_key,
        )
        if demo_cache_enabled and job.status == AiJobStatus.QUEUED:
            self._complete_from_demo_cache(job)
        return job, created

    @staticmethod
    def _current_demo_job(*, prd, user_id, persona, question_versions):
        candidates = AiJob.objects.filter(
            prd=prd,
            user_id=user_id,
            feature_type=AiFeatureType.PRD_EVALUATION,
            action_type=AiActionType.EVALUATION,
            status=AiJobStatus.SUCCEEDED,
            input_data__persona=persona,
            input_data__demo_cache=True,
        ).order_by("-finished_at", "-created_at")
        return next(
            (
                job
                for job in candidates
                if (job.input_data.get("question_versions") or {}) == question_versions
            ),
            None,
        )

    @staticmethod
    @transaction.atomic
    def _complete_from_demo_cache(job: AiJob) -> None:
        job = AiJob.objects.select_for_update().select_related("prompt", "prd").get(pk=job.pk)
        if job.status != AiJobStatus.QUEUED:
            return
        job.input_data["demo_cache"] = True
        raw_output = _build_demo_evaluation(job.input_data)
        job.output_data = PrdEvaluationResultProcessor().process(job=job, output=raw_output)
        job.output_data["source"] = "demo_cache"
        job.status = AiJobStatus.SUCCEEDED
        job.attempt_count = 1
        job.started_at = timezone.now()
        job.finished_at = job.started_at
        job.save(
            update_fields=[
                "input_data",
                "output_data",
                "status",
                "attempt_count",
                "started_at",
                "finished_at",
                "updated_at",
            ]
        )
        AiUsageLog.objects.create(
            job=job,
            prd=job.prd,
            user_id=job.user_id,
            feature_type=job.feature_type,
            action_type=job.action_type,
            status=AiUsageStatus.SUCCESS,
            total_tokens=0,
            cost_usd=Decimal("0"),
            model="development-demo-cache",
            prompt_version=job.prompt.version,
            attempt_number=1,
        )

    @staticmethod
    def latest(
        *,
        prd: Prd,
        user_id: int,
        jobs_by_persona: dict[str, AiJob] | None = None,
    ) -> AiJob | None:
        jobs = (
            jobs_by_persona
            if jobs_by_persona is not None
            else PrdEvaluationService.latest_by_persona(prd=prd, user_id=user_id)
        ).values()
        active_statuses = {
            AiJobStatus.QUEUED,
            AiJobStatus.RUNNING,
            AiJobStatus.RETRY_WAIT,
            AiJobStatus.CANCEL_REQUESTED,
        }
        active = [job for job in jobs if job.status in active_statuses]
        if active:
            return max(active, key=lambda job: (job.created_at, str(job.pk)))
        succeeded = [job for job in jobs if job.status == AiJobStatus.SUCCEEDED]
        return (
            max(succeeded, key=lambda job: (job.finished_at or job.created_at, str(job.pk)))
            if succeeded
            else None
        )

    @staticmethod
    def latest_by_persona(*, prd: Prd, user_id: int) -> dict[str, AiJob]:
        """Return one restorable or active diagnosis for every supported perspective."""
        active_statuses = [
            AiJobStatus.QUEUED,
            AiJobStatus.RUNNING,
            AiJobStatus.RETRY_WAIT,
            AiJobStatus.CANCEL_REQUESTED,
        ]
        candidates = (
            AiJob.objects.filter(
                prd=prd,
                feature_type=AiFeatureType.PRD_EVALUATION,
                action_type=AiActionType.EVALUATION,
            )
            .filter(
                Q(user_id=user_id, status__in=active_statuses) | Q(status=AiJobStatus.SUCCEEDED)
            )
            .select_related("prompt")
            .order_by("-created_at", "-id")
        )
        selected: dict[str, AiJob] = {}
        for job in candidates:
            persona = job.input_data.get("persona")
            if persona not in EVALUATION_PERSONAS:
                continue
            current = selected.get(persona)
            if current is None:
                selected[persona] = job
                continue
            job_is_active = job.user_id == user_id and job.status in active_statuses
            current_is_active = current.user_id == user_id and current.status in active_statuses
            if job_is_active and not current_is_active:
                selected[persona] = job
        return selected

    @staticmethod
    def is_current(job: AiJob) -> bool:
        snapshot = job.input_data.get("question_versions") or {}
        current = {
            str(question_id): version
            for question_id, version in PrdQuestion.objects.filter(
                section__prd=job.prd,
                section__is_deleted=False,
                is_deleted=False,
                is_held=False,
            ).values_list("id", "version")
        }
        return snapshot == current


class PrdEvaluationResultProcessor:
    def process(self, *, job: AiJob, output: dict[str, Any]) -> dict[str, Any]:
        if (
            job.feature_type != AiFeatureType.PRD_EVALUATION
            or job.action_type != AiActionType.EVALUATION
        ):
            return output
        expected_section_ids = {section["id"] for section in job.input_data["context"]["sections"]}
        section_rows = output.get("sections")
        if not isinstance(section_rows, list):
            raise AiOutputValidationError("PRD evaluation sections must be an array.")
        returned_ids = [row.get("section_id") for row in section_rows]
        if len(returned_ids) != len(set(returned_ids)):
            raise AiOutputValidationError("PRD evaluation repeated a section identifier.")
        if set(returned_ids) != expected_section_ids:
            raise AiOutputValidationError("PRD evaluation must cover every current section once.")
        return {
            "persona": job.input_data["persona"],
            "persona_label": job.input_data["persona_label"],
            "overall_score": output["overall_score"],
            "summary": sanitize_ai_markdown(output["summary"]),
            "strengths": [sanitize_ai_markdown(value) for value in output["strengths"]],
            "improvements": [sanitize_ai_markdown(value) for value in output["improvements"]],
            "sections": [
                {
                    "section_id": row["section_id"],
                    "score": row["score"],
                    "status": row["status"],
                    "feedback": sanitize_ai_markdown(row["feedback"]),
                    "missing_points": [
                        sanitize_ai_markdown(value) for value in row["missing_points"]
                    ],
                }
                for row in section_rows
            ],
        }


def _build_demo_evaluation(input_data: dict[str, Any]) -> dict[str, Any]:
    """Create a deterministic development preview without pretending to call AI."""
    persona = input_data["persona"]
    sections = input_data["context"]["sections"]
    persona_copy = {
        "pm": (
            "사용자 문제와 성공 기준을 더 구체적으로 연결해 보세요.",
            "사용자 가치와 검증 가능한 성공 지표",
        ),
        "engineering": (
            "데이터 흐름, 예외 상황과 구현 범위를 더 명확히 적어 보세요.",
            "연동 조건과 기술적 예외 처리",
        ),
        "investor": (
            "차별점과 핵심 가설을 수치로 검증할 방법을 보완해 보세요.",
            "대안 대비 차별성과 검증 계획",
        ),
    }
    guidance, missing_point = persona_copy[persona]
    rows = []
    for section in sections:
        questions = section.get("questions", [])
        answered = [q for q in questions if str(q.get("answer") or "").strip()]
        answer_chars = sum(len(str(q.get("answer") or "").strip()) for q in answered)
        coverage = len(answered) / len(questions) if questions else 0
        detail = min(1, answer_chars / max(1, len(questions) * 80))
        score = round(15 + coverage * 65 + detail * 20)
        if score >= 80:
            status = "good"
            feedback = (
                "핵심 내용이 구체적으로 작성되어 있습니다. 검증 기준을 마지막으로 점검해 보세요."
            )
            missing_points = []
        elif score >= 45:
            status = "needs_improvement"
            feedback = guidance
            missing_points = [missing_point]
        else:
            status = "missing"
            feedback = "비어 있거나 짧은 답변이 많습니다. 질문별 근거를 먼저 작성해 주세요."
            missing_points = [missing_point, "질문별 구체적인 답변"]
        rows.append(
            {
                "section_id": section["id"],
                "score": score,
                "status": status,
                "feedback": feedback,
                "missing_points": missing_points,
            }
        )
    overall_score = round(sum(row["score"] for row in rows) / len(rows)) if rows else 0
    return {
        "overall_score": overall_score,
        "summary": (
            "현재 작성된 답변을 기준으로 한 개발용 미리보기입니다. "
            + ("핵심 항목이 잘 정리되어 있습니다." if overall_score >= 70 else guidance)
        ),
        "strengths": ["작성된 질문과 답변 범위를 일관된 기준으로 확인했습니다."],
        "improvements": [guidance],
        "sections": rows,
    }
