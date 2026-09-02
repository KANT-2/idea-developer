from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class AiFeatureType(models.TextChoices):
    BRAINSTORM_ANALYSIS = "BRAINSTORM_ANALYSIS", "브레인스토밍 분석"
    BRAINSTORM_CLASSIFICATION = "BRAINSTORM_CLASSIFICATION", "브레인스토밍 분류"
    BRAINSTORM_PRD_APPLY = "BRAINSTORM_PRD_APPLY", "브레인스토밍 PRD 반영"
    CONTRIBUTION_EVALUATION = "CONTRIBUTION_EVALUATION", "기여도 평가"
    COACHING = "COACHING", "AI 코칭"


class AiActionType(models.TextChoices):
    ANALYSIS = "analysis", "분석"
    CLASSIFICATION = "classification", "분류"
    PRD_APPLY = "prd_apply", "PRD 반영"
    CONTRIBUTION_EVALUATION = "contribution_evaluation", "기여도 평가"
    CHAT = "chat", "대화"
    DRAFT = "draft", "초안"


class AiUsageStatus(models.TextChoices):
    SUCCESS = "success", "성공"
    FAILED = "failed", "실패"
    CANCELLED = "cancelled", "취소"


class AiJobStatus(models.TextChoices):
    QUEUED = "queued", "대기"
    RUNNING = "running", "실행 중"
    RETRY_WAIT = "retry_wait", "재시도 대기"
    CANCEL_REQUESTED = "cancel_requested", "취소 요청"
    SUCCEEDED = "succeeded", "성공"
    FAILED = "failed", "실패"
    CANCELLED = "cancelled", "취소됨"
    TIMED_OUT = "timed_out", "시간 초과"


class AiConversationMessageRole(models.TextChoices):
    USER = "user", "사용자"
    ASSISTANT = "assistant", "AI 코치"


class AiPrompt(models.Model):
    feature_type = models.CharField(max_length=32, choices=AiFeatureType.choices)
    version = models.PositiveIntegerField()
    system_instructions = models.TextField()
    output_schema = models.JSONField(default=dict)
    model = models.CharField(max_length=128)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_prompts"
        ordering = ["feature_type", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["feature_type", "version"],
                name="uniq_ai_prompt_feature_version",
            ),
            models.UniqueConstraint(
                fields=["feature_type"],
                condition=Q(is_active=True),
                name="uniq_active_ai_prompt_feature",
            ),
            models.CheckConstraint(
                condition=Q(feature_type__in=AiFeatureType.values),
                name="ai_prompt_feature_valid",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="ai_prompt_version_positive",
            ),
            models.CheckConstraint(
                condition=~Q(system_instructions=""),
                name="ai_prompt_system_not_blank",
            ),
            models.CheckConstraint(
                condition=~Q(model=""),
                name="ai_prompt_model_not_blank",
            ),
        ]


class AiUsageLog(models.Model):
    job = models.ForeignKey(
        "ai.AiJob",
        on_delete=models.SET_NULL,
        related_name="usage_logs",
        null=True,
        blank=True,
    )
    prd = models.ForeignKey(
        "prds.Prd",
        on_delete=models.CASCADE,
        related_name="ai_usage_logs",
    )
    user_id = models.PositiveBigIntegerField()
    feature_type = models.CharField(max_length=32, choices=AiFeatureType.choices)
    action_type = models.CharField(max_length=32, choices=AiActionType.choices)
    status = models.CharField(max_length=16, choices=AiUsageStatus.choices)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("0"))
    model = models.CharField(max_length=128, default="unknown")
    prompt_version = models.PositiveIntegerField(default=1)
    attempt_number = models.PositiveIntegerField(default=1)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_usage_logs"
        indexes = [
            models.Index(
                fields=["prd", "feature_type", "action_type", "status"],
                name="ai_usage_home_kpi_idx",
            ),
            models.Index(
                fields=["user_id", "feature_type", "-created_at"],
                name="ai_usage_limit_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(user_id__gt=0),
                name="ai_usage_user_id_positive",
            ),
            models.CheckConstraint(
                condition=Q(feature_type__in=AiFeatureType.values),
                name="ai_usage_feature_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(action_type__in=AiActionType.values),
                name="ai_usage_action_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        feature_type=AiFeatureType.BRAINSTORM_ANALYSIS,
                        action_type=AiActionType.ANALYSIS,
                    )
                    | Q(
                        feature_type=AiFeatureType.BRAINSTORM_CLASSIFICATION,
                        action_type=AiActionType.CLASSIFICATION,
                    )
                    | Q(
                        feature_type=AiFeatureType.BRAINSTORM_PRD_APPLY,
                        action_type=AiActionType.PRD_APPLY,
                    )
                    | Q(
                        feature_type=AiFeatureType.CONTRIBUTION_EVALUATION,
                        action_type=AiActionType.CONTRIBUTION_EVALUATION,
                    )
                    | Q(
                        feature_type=AiFeatureType.COACHING,
                        action_type__in=[AiActionType.CHAT, AiActionType.DRAFT],
                    )
                ),
                name="ai_usage_feature_action_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=AiUsageStatus.values),
                name="ai_usage_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(total_tokens__gte=F("input_tokens") + F("output_tokens")),
                name="ai_usage_token_total_valid",
            ),
            models.CheckConstraint(
                condition=Q(cost_usd__gte=0),
                name="ai_usage_cost_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(prompt_version__gte=1),
                name="ai_usage_prompt_version_positive",
            ),
            models.CheckConstraint(
                condition=Q(attempt_number__gte=1),
                name="ai_usage_attempt_positive",
            ),
            models.CheckConstraint(
                condition=~Q(model=""),
                name="ai_usage_model_not_blank",
            ),
        ]


class AiJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prd = models.ForeignKey(
        "prds.Prd",
        on_delete=models.CASCADE,
        related_name="ai_jobs",
    )
    prompt = models.ForeignKey(
        AiPrompt,
        on_delete=models.PROTECT,
        related_name="jobs",
    )
    user_id = models.PositiveBigIntegerField()
    feature_type = models.CharField(max_length=32, choices=AiFeatureType.choices)
    action_type = models.CharField(max_length=32, choices=AiActionType.choices)
    status = models.CharField(
        max_length=24,
        choices=AiJobStatus.choices,
        default=AiJobStatus.QUEUED,
    )
    idempotency_key = models.CharField(max_length=128)
    input_data = models.JSONField(default=dict)
    output_data = models.JSONField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    timeout_seconds = models.PositiveIntegerField(default=30)
    available_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=128, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_jobs"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["status", "available_at", "created_at"],
                name="ai_job_claim_idx",
            ),
            models.Index(
                fields=["status", "lease_expires_at"],
                name="ai_job_lease_idx",
            ),
            models.Index(
                fields=["user_id", "feature_type", "-created_at"],
                name="ai_job_user_limit_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "prd", "feature_type", "idempotency_key"],
                name="uniq_ai_job_request",
            ),
            models.CheckConstraint(
                condition=Q(user_id__gt=0),
                name="ai_job_user_positive",
            ),
            models.CheckConstraint(
                condition=Q(feature_type__in=AiFeatureType.values),
                name="ai_job_feature_valid",
            ),
            models.CheckConstraint(
                condition=Q(action_type__in=AiActionType.values),
                name="ai_job_action_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        feature_type=AiFeatureType.BRAINSTORM_ANALYSIS,
                        action_type=AiActionType.ANALYSIS,
                    )
                    | Q(
                        feature_type=AiFeatureType.BRAINSTORM_CLASSIFICATION,
                        action_type=AiActionType.CLASSIFICATION,
                    )
                    | Q(
                        feature_type=AiFeatureType.BRAINSTORM_PRD_APPLY,
                        action_type=AiActionType.PRD_APPLY,
                    )
                    | Q(
                        feature_type=AiFeatureType.CONTRIBUTION_EVALUATION,
                        action_type=AiActionType.CONTRIBUTION_EVALUATION,
                    )
                    | Q(
                        feature_type=AiFeatureType.COACHING,
                        action_type__in=[AiActionType.CHAT, AiActionType.DRAFT],
                    )
                ),
                name="ai_job_feature_action_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=AiJobStatus.values),
                name="ai_job_status_valid",
            ),
            models.CheckConstraint(
                condition=~Q(idempotency_key=""),
                name="ai_job_key_not_blank",
            ),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1),
                name="ai_job_max_attempts_positive",
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__lte=F("max_attempts")),
                name="ai_job_attempts_within_limit",
            ),
            models.CheckConstraint(
                condition=Q(timeout_seconds__gte=1),
                name="ai_job_timeout_positive",
            ),
        ]


class AiChatHistory(models.Model):
    prd = models.ForeignKey(
        "prds.Prd",
        on_delete=models.CASCADE,
        related_name="ai_chat_history",
    )
    user_id = models.PositiveBigIntegerField()
    prompt = models.TextField()
    response = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_chat_histories"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["prd", "-created_at"], name="ai_chat_prd_created_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(user_id__gt=0),
                name="ai_chat_user_id_positive",
            )
        ]


class AiCoachConversation(models.Model):
    prd = models.ForeignKey(
        "prds.Prd",
        on_delete=models.CASCADE,
        related_name="ai_coach_conversations",
    )
    section = models.ForeignKey(
        "prds.PrdSection",
        on_delete=models.CASCADE,
        related_name="ai_coach_conversations",
        null=True,
        blank=True,
    )
    user_id = models.PositiveBigIntegerField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_coach_conversations"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["expires_at"], name="ai_coach_expiry_idx"),
            models.Index(fields=["prd", "user_id"], name="ai_coach_prd_user_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["prd", "section", "user_id"],
                condition=Q(section__isnull=False),
                name="uniq_ai_coach_section_user",
            ),
            models.UniqueConstraint(
                fields=["prd", "user_id"],
                condition=Q(section__isnull=True),
                name="uniq_ai_coach_whole_user",
            ),
            models.CheckConstraint(
                condition=Q(user_id__gt=0),
                name="ai_coach_user_positive",
            ),
        ]


class AiCoachMessage(models.Model):
    conversation = models.ForeignKey(
        AiCoachConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    job = models.ForeignKey(
        AiJob,
        on_delete=models.SET_NULL,
        related_name="coach_messages",
        null=True,
        blank=True,
    )
    sequence = models.PositiveBigIntegerField()
    role = models.CharField(max_length=16, choices=AiConversationMessageRole.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_coach_messages"
        ordering = ["sequence", "id"]
        indexes = [
            models.Index(
                fields=["conversation", "role", "-sequence"],
                name="ai_coach_recent_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"],
                name="uniq_ai_coach_message_sequence",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1),
                name="ai_coach_message_sequence_positive",
            ),
            models.CheckConstraint(
                condition=Q(role__in=AiConversationMessageRole.values),
                name="ai_coach_message_role_valid",
            ),
            models.CheckConstraint(
                condition=~Q(content=""),
                name="ai_coach_message_content_not_blank",
            ),
        ]
