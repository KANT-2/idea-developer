from __future__ import annotations

from typing import Protocol

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .detail import PrdAccess
from .models import (
    Prd,
    PrdComment,
    PrdCommentType,
    PrdParticipantRole,
    PrdQuestion,
)


class CommentStatePolicy(Protocol):
    def enforce_create(self, *, access: PrdAccess, comment_type: str): ...

    def enforce_modify(self, *, access: PrdAccess, comment: PrdComment): ...


class CompletionCommentStatePolicy:
    """Completed PRDs accept only tutor post-completion review comments."""

    def enforce_create(self, *, access: PrdAccess, comment_type: str):
        if access.prd.status != "completed":
            if comment_type == PrdCommentType.POST_COMPLETION_REVIEW:
                raise PermissionDenied("Post-completion review comments require a completed PRD.")
            return
        if (
            access.role != PrdParticipantRole.TUTOR
            or comment_type != PrdCommentType.POST_COMPLETION_REVIEW
        ):
            raise PermissionDenied("Completed PRDs only accept tutor review comments.")

    def enforce_modify(self, *, access: PrdAccess, comment: PrdComment):
        if access.prd.status != "completed":
            return
        if (
            access.role != PrdParticipantRole.TUTOR
            or comment.comment_type != PrdCommentType.POST_COMPLETION_REVIEW
        ):
            raise PermissionDenied("Comments are locked while the PRD is completed.")


class CommentRolePolicy:
    def normalize_type(self, *, role: str | None, requested_type: str | None) -> str:
        if role in {PrdParticipantRole.OWNER, PrdParticipantRole.EDITOR}:
            comment_type = requested_type or PrdCommentType.GENERAL
            if comment_type != PrdCommentType.GENERAL:
                raise PermissionDenied("Owners and editors create general comments.")
            return comment_type
        if role == PrdParticipantRole.TUTOR:
            comment_type = requested_type or PrdCommentType.GUIDANCE
            if comment_type not in {
                PrdCommentType.GUIDANCE,
                PrdCommentType.REVIEW,
                PrdCommentType.POST_COMPLETION_REVIEW,
            }:
                raise PermissionDenied("Tutors create guidance or review comments.")
            return comment_type
        raise PermissionDenied("The current PRD role cannot comment.")

    @staticmethod
    def contribution_eligible(*, role: str, comment_type: str) -> bool:
        return role in {PrdParticipantRole.OWNER, PrdParticipantRole.EDITOR} and (
            comment_type == PrdCommentType.GENERAL
        )


class PrdCommentService:
    def __init__(
        self,
        *,
        role_policy: CommentRolePolicy | None = None,
        state_policy: CommentStatePolicy | None = None,
    ):
        self.role_policy = role_policy or CommentRolePolicy()
        self.state_policy = state_policy or CompletionCommentStatePolicy()

    @transaction.atomic
    def create(
        self,
        *,
        access: PrdAccess,
        author_user_id: int,
        content: str,
        section_question_id: int | None,
        requested_type: str | None,
    ) -> PrdComment:
        normalized_content = self._validate_content(content)
        if access.role is None:
            raise PermissionDenied("A team viewer cannot comment.")
        comment_type = self.role_policy.normalize_type(
            role=access.role,
            requested_type=requested_type,
        )
        self.state_policy.enforce_create(access=access, comment_type=comment_type)
        question = self._get_question(access.prd, section_question_id)
        comment = PrdComment.objects.create(
            prd=access.prd,
            section_question=question,
            author_user_id=author_user_id,
            author_role_at_created=access.role,
            comment_type=comment_type,
            content=normalized_content,
            is_contribution_eligible=self.role_policy.contribution_eligible(
                role=access.role,
                comment_type=comment_type,
            ),
        )
        self._touch_prd(access.prd)
        return comment

    @transaction.atomic
    def update(
        self,
        *,
        access: PrdAccess,
        comment: PrdComment,
        actor_user_id: int,
        content: str,
    ) -> PrdComment:
        self._enforce_author(comment=comment, actor_user_id=actor_user_id)
        self.state_policy.enforce_modify(access=access, comment=comment)
        comment.content = self._validate_content(content)
        comment.save(update_fields=["content", "updated_at"])
        self._touch_prd(access.prd)
        return comment

    @transaction.atomic
    def delete(self, *, access: PrdAccess, comment: PrdComment, actor_user_id: int):
        self._enforce_author(comment=comment, actor_user_id=actor_user_id)
        self.state_policy.enforce_modify(access=access, comment=comment)
        comment.is_deleted = True
        comment.deleted_at = timezone.now()
        comment.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
        self._touch_prd(access.prd)

    @staticmethod
    def _validate_content(content):
        if not isinstance(content, str) or not content.strip():
            raise ValidationError({"content": "코멘트 내용을 입력해 주세요."})
        return content.strip()

    @staticmethod
    def _get_question(prd, question_id):
        if question_id is None:
            return None
        try:
            return PrdQuestion.objects.get(
                pk=question_id,
                section__prd=prd,
                section__is_deleted=False,
                is_deleted=False,
            )
        except PrdQuestion.DoesNotExist as exc:
            raise ValidationError(
                {"section_question_id": "이 PRD의 활성 질문이 아닙니다."}
            ) from exc

    @staticmethod
    def _enforce_author(*, comment, actor_user_id):
        if comment.author_user_id != actor_user_id:
            raise PermissionDenied("Only the comment author can modify it.")

    @staticmethod
    def _touch_prd(prd):
        now = timezone.now()
        Prd.objects.filter(pk=prd.pk).update(updated_at=now)
        prd.updated_at = now
