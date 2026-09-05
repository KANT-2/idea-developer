from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.views.decorators.http import require_GET, require_http_methods

from apps.ai.contribution import ContributionEvaluationService
from apps.ai.exceptions import AiJobNotRetryable, AiPromptNotConfigured, AiUsageLimitExceeded
from apps.ai.models import (
    AiCoachMessage,
    AiConversationMessageRole,
    AiUsageLog,
    ContributionEvaluation,
)
from apps.common.responses import api_success
from apps.integration.exceptions import IntegrationError

from .detail import PrdNotFound
from .detail_views import (
    _error_response,
    _get_access,
    _paginate,
    _pagination,
    _participant_summaries,
    _request_id,
    _require_authentication,
    get_integration_repository,
)


def _paginated_detail_endpoint(request, prd_id, queryset_factory, serializer):
    if response := _require_authentication(request):
        return response
    try:
        _, access = _get_access(request, prd_id)
        page, page_size = _pagination(request)
        data = _paginate(
            queryset_factory(access.prd),
            page=page,
            page_size=page_size,
            serializer=serializer,
        )
        return api_success(data, request_id=_request_id(request))
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error_response(request, exc)


@require_GET
def ai_usage_history(request, prd_id):
    return _paginated_detail_endpoint(
        request,
        prd_id,
        lambda prd: AiUsageLog.objects.filter(prd=prd).order_by("-created_at", "-id"),
        lambda row: {
            "id": row.id,
            "user_id": row.user_id,
            "feature_type": row.feature_type,
            "action_type": row.action_type,
            "status": row.status,
            "total_tokens": row.total_tokens,
            "created_at": row.created_at.isoformat(),
        },
    )


@require_GET
def ai_chat_history(request, prd_id):
    job_prompt = (
        AiCoachMessage.objects.filter(
            conversation_id=OuterRef("conversation_id"),
            job_id=OuterRef("job_id"),
            role=AiConversationMessageRole.USER,
            sequence__lt=OuterRef("sequence"),
        )
        .order_by("-sequence")
        .values("content")[:1]
    )
    previous_prompt = (
        AiCoachMessage.objects.filter(
            conversation_id=OuterRef("conversation_id"),
            role=AiConversationMessageRole.USER,
            sequence__lt=OuterRef("sequence"),
        )
        .order_by("-sequence")
        .values("content")[:1]
    )
    return _paginated_detail_endpoint(
        request,
        prd_id,
        lambda prd: (
            AiCoachMessage.objects.filter(
                conversation__prd=prd,
                role=AiConversationMessageRole.ASSISTANT,
            )
            .select_related("conversation")
            .annotate(
                prompt_text=Coalesce(
                    Subquery(job_prompt),
                    Subquery(previous_prompt),
                )
            )
            .order_by("-created_at", "-id")
        ),
        lambda row: {
            "id": row.id,
            "user_id": row.conversation.user_id,
            "prompt": row.prompt_text or "",
            "response": row.content,
            "created_at": row.created_at.isoformat(),
        },
    )


@require_GET
def change_history(request, prd_id):
    return _paginated_detail_endpoint(
        request,
        prd_id,
        lambda prd: prd.change_history.all(),
        lambda row: {
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "event_type": row.event_type,
            "before_data": row.before_data,
            "after_data": row.after_data,
            "created_at": row.created_at.isoformat(),
        },
    )


@require_GET
def contribution_results(request, prd_id):
    if response := _require_authentication(request):
        return response
    try:
        _, access = _get_access(request, prd_id)
        if not access.is_admin:
            raise PermissionDenied("기여도 결과는 관리자만 조회할 수 있습니다.")
        evaluations = (
            ContributionEvaluation.objects.filter(prd=access.prd)
            .select_related("job")
            .prefetch_related("user_scores", "comment_scores")
            .order_by("-calculation_version")
        )
        user_ids = tuple(
            dict.fromkeys(
                score.user_id
                for evaluation in evaluations
                for score in evaluation.user_scores.all()
            )
        )
        display_names = _participant_summaries(
            get_integration_repository(),
            user_ids=user_ids,
            round_id=access.prd.round_id,
        )
        return api_success(
            {
                "items": [
                    _serialize_contribution(row, display_names=display_names) for row in evaluations
                ]
            },
            request_id=_request_id(request),
        )
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error_response(request, exc)


@require_http_methods(["POST"])
def retry_contribution(request, prd_id, calculation_version):
    if response := _require_authentication(request):
        return response
    try:
        _, access = _get_access(request, prd_id)
        if not access.is_admin:
            raise PermissionDenied("기여도 재평가는 관리자만 실행할 수 있습니다.")
        try:
            evaluation = ContributionEvaluation.objects.get(
                prd=access.prd,
                calculation_version=calculation_version,
            )
        except ContributionEvaluation.DoesNotExist as exc:
            raise PrdNotFound from exc
        evaluation = ContributionEvaluationService().retry_same_input(
            evaluation=evaluation,
            access=access,
        )
        display_names = _participant_summaries(
            get_integration_repository(),
            user_ids=tuple(score.user_id for score in evaluation.user_scores.all()),
            round_id=access.prd.round_id,
        )
        return api_success(
            _serialize_contribution(evaluation, display_names=display_names),
            status=202,
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        AiJobNotRetryable,
        AiPromptNotConfigured,
        AiUsageLimitExceeded,
    ) as exc:
        return _error_response(request, exc)


def _serialize_contribution(evaluation, *, display_names=None):
    display_names = display_names or {}
    return {
        "calculation_version": evaluation.calculation_version,
        "prd_version": evaluation.prd_version,
        "status": evaluation.status,
        "input_fingerprint": evaluation.input_fingerprint,
        "model": evaluation.model or None,
        "prompt_version": evaluation.prompt_version,
        "target_node_ids": evaluation.target_node_ids,
        "target_comment_ids": evaluation.target_comment_ids,
        "evidence": evaluation.evidence,
        "failure_code": evaluation.failure_code or None,
        "calculated_at": (
            evaluation.calculated_at.isoformat() if evaluation.calculated_at else None
        ),
        "scores": [
            {
                "user_id": score.user_id,
                "display_name": display_names.get(score.user_id, "알 수 없는 참여자"),
                "participant_id": score.participant_id,
                "memo_raw": score.memo_raw,
                "memo_contribution": float(score.memo_contribution),
                "comment_raw": float(score.comment_raw),
                "comment_contribution": float(score.comment_contribution),
                "total_score": float(score.total_score),
                "node_ids": score.node_ids,
                "comment_ids": score.comment_ids,
                "evidence": score.evidence,
            }
            for score in evaluation.user_scores.all()
        ],
        "comment_scores": [
            {
                "comment_id": score.comment_id,
                "author_user_id": score.author_user_id,
                "reflection_score": float(score.reflection_score),
                "matched_question_ids": score.matched_question_ids,
                "evidence": score.evidence,
                "reason": score.reason,
                "confidence": float(score.confidence),
            }
            for score in evaluation.comment_scores.all()
        ],
    }
