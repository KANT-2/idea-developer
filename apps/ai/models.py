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
    PRD_EVALUATION = "PRD_EVALUATION", "PRD 충족도 진단"


class AiActionType(models.TextChoices):
    ANALYSIS = "analysis", "분석"
    CLASSIFICATION = "classification", "분류"
    PRD_APPLY = "prd_apply", "PRD 반영"
    CONTRIBUTION_EVALUATION = "contribution_evaluation", "기여도 평가"
    CHAT = "chat", "대화"
    DRAFT = "draft", "초안"
    EVALUATION = "evaluation", "충족도 진단"


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


class ContributionEvaluationStatus(models.TextChoices):
    PENDING = "pending", "계산 중"
    SUCCEEDED = "succeeded", "완료"
    FAILED = "failed", "실패"


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
                    | Q(
                        feature_type=AiFeatureType.PRD_EVALUATION,
                        action_type=AiActionType.EVALUATION,
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
    request_fingerprint = models.CharField(max_length=64, blank=True, default="", db_index=True)
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
            models.CheckConstraint(condition=Q(user_id__gt=0), name="ai_job_user_positive"),
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
                    | Q(
                        feature_type=AiFeatureType.PRD_EVALUATION,
                        action_type=AiActionType.EVALUATION,
                    )
                ),
                name="ai_job_feature_action_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=AiJobStatus.values), name="ai_job_status_valid"
            ),
            models.CheckConstraint(condition=~Q(idempotency_key=""), name="ai_job_key_not_blank"),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1), name="ai_job_max_attempts_positive"
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__lte=F("max_attempts")),
                name="ai_job_attempts_within_limit",
            ),
            models.CheckConstraint(
                condition=Q(timeout_seconds__gte=1), name="ai_job_timeout_positive"
            ),
        ]


class ContributionEvaluation(models.Model):
    prd = models.ForeignKey(
        "prds.Prd", on_delete=models.CASCADE, related_name="contribution_evaluations"
    )
    completion_audit = models.OneToOneField(
        "prds.PrdStatusAuditLog",
        on_delete=models.PROTECT,
        related_name="contribution_evaluation",
    )
    job = models.OneToOneField(
        AiJob,
        on_delete=models.SET_NULL,
        related_name="contribution_evaluation",
        null=True,
        blank=True,
    )
    calculation_version = models.PositiveIntegerField()
    prd_version = models.PositiveBigIntegerField()
    status = models.CharField(
        max_length=16,
        choices=ContributionEvaluationStatus.choices,
        default=ContributionEvaluationStatus.PENDING,
    )
    input_fingerprint = models.CharField(max_length=64)
    input_snapshot = models.JSONField(default=dict)
    model = models.CharField(max_length=128, blank=True)
    prompt_version = models.PositiveIntegerField(null=True, blank=True)
    target_node_ids = models.JSONField(default=list)
    target_comment_ids = models.JSONField(default=list)
    evidence = models.JSONField(default=dict)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.TextField(blank=True)
    calculated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contribution_evaluations"
        ordering = ["prd", "calculation_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["prd", "calculation_version"],
                name="uniq_contribution_calculation_version",
            ),
            models.CheckConstraint(
                condition=Q(calculation_version__gte=1),
                name="contribution_calculation_version_positive",
            ),
            models.CheckConstraint(
                condition=Q(prd_version__gte=1),
                name="contribution_prd_version_positive",
            ),
            models.CheckConstraint(
                condition=Q(status__in=ContributionEvaluationStatus.values),
                name="contribution_status_valid",
            ),
            models.CheckConstraint(
                condition=~Q(input_fingerprint=""),
                name="contribution_fingerprint_not_blank",
            ),
        ]


class ContributionUserScore(models.Model):
    evaluation = models.ForeignKey(
        ContributionEvaluation, on_delete=models.CASCADE, related_name="user_scores"
    )
    user_id = models.PositiveBigIntegerField()
    participant_id = models.PositiveBigIntegerField()
    memo_raw = models.DecimalField(max_digits=12, decimal_places=4)
    memo_contribution = models.DecimalField(max_digits=7, decimal_places=4)
    comment_raw = models.DecimalField(max_digits=12, decimal_places=4)
    comment_contribution = models.DecimalField(max_digits=7, decimal_places=4)
    total_score = models.DecimalField(max_digits=7, decimal_places=4)
    node_ids = models.JSONField(default=list)
    comment_ids = models.JSONField(default=list)
    evidence = models.JSONField(default=dict)

    class Meta:
        db_table = "contribution_user_scores"
        ordering = ["evaluation", "user_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["evaluation", "user_id"],
                name="uniq_contribution_user_score",
            ),
            models.CheckConstraint(condition=Q(user_id__gt=0), name="contribution_user_positive"),
            models.CheckConstraint(
                condition=Q(participant_id__gt=0),
                name="contribution_participant_positive",
            ),
            models.CheckConstraint(
                condition=Q(memo_contribution__gte=0, memo_contribution__lte=100),
                name="contribution_memo_score_range",
            ),
            models.CheckConstraint(
                condition=Q(comment_contribution__gte=0, comment_contribution__lte=100),
                name="contribution_comment_score_range",
            ),
            models.CheckConstraint(
                condition=Q(total_score__gte=0, total_score__lte=100),
                name="contribution_total_score_range",
            ),
        ]


class ContributionCommentScore(models.Model):
    evaluation = models.ForeignKey(
        ContributionEvaluation, on_delete=models.CASCADE, related_name="comment_scores"
    )
    comment = models.ForeignKey(
        "prds.PrdComment", on_delete=models.PROTECT, related_name="contribution_scores"
    )
    author_user_id = models.PositiveBigIntegerField()
    reflection_score = models.DecimalField(max_digits=7, decimal_places=4)
    matched_question_ids = models.JSONField(default=list)
    evidence = models.JSONField(default=list)
    reason = models.TextField()
    confidence = models.DecimalField(max_digits=5, decimal_places=4)

    class Meta:
        db_table = "contribution_comment_scores"
        ordering = ["evaluation", "comment_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["evaluation", "comment"],
                name="uniq_contribution_comment_score",
            ),
            models.CheckConstraint(
                condition=Q(author_user_id__gt=0),
                name="contribution_comment_author_positive",
            ),
            models.CheckConstraint(
                condition=Q(reflection_score__gte=0, reflection_score__lte=100),
                name="contribution_reflection_score_range",
            ),
            models.CheckConstraint(
                condition=Q(confidence__gte=0, confidence__lte=1),
                name="contribution_confidence_range",
            ),
        ]


class AiPrdApplyScope(models.TextChoices):
    SECTION = "section", "섹션"
    ALL = "all", "전체 PRD"


class AiPrdApplyRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prd = models.ForeignKey(
        "prds.Prd", on_delete=models.CASCADE, related_name="ai_prd_apply_records"
    )
    canvas = models.ForeignKey(
        "brainstorm.BrainstormCanvas",
        on_delete=models.CASCADE,
        related_name="prd_apply_records",
    )
    preview_job = models.OneToOneField(
        AiJob, on_delete=models.PROTECT, related_name="prd_apply_record"
    )
    section = models.ForeignKey(
        "prds.PrdSection",
        on_delete=models.PROTECT,
        related_name="ai_prd_apply_records",
        null=True,
        blank=True,
    )
    scope = models.CharField(max_length=16, choices=AiPrdApplyScope.choices)
    actor_user_id = models.PositiveBigIntegerField()
    idempotency_key = models.CharField(max_length=128)
    model = models.CharField(max_length=128)
    prompt_version = models.PositiveIntegerField()
    unused_node_ids = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_prd_apply_records"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["prd", "-created_at"], name="ai_apply_prd_created_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["prd", "actor_user_id", "idempotency_key"],
                name="uniq_ai_prd_apply_request",
            ),
            models.CheckConstraint(
                condition=Q(scope__in=AiPrdApplyScope.values),
                name="ai_prd_apply_scope_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(scope=AiPrdApplyScope.SECTION, section__isnull=False)
                    | Q(scope=AiPrdApplyScope.ALL, section__isnull=True)
                ),
                name="ai_prd_apply_scope_section_valid",
            ),
            models.CheckConstraint(
                condition=Q(actor_user_id__gt=0), name="ai_prd_apply_actor_positive"
            ),
            models.CheckConstraint(
                condition=Q(prompt_version__gte=1),
                name="ai_prd_apply_prompt_version_positive",
            ),
            models.CheckConstraint(
                condition=~Q(idempotency_key=""), name="ai_prd_apply_key_not_blank"
            ),
            models.CheckConstraint(condition=~Q(model=""), name="ai_prd_apply_model_not_blank"),
        ]


class AiPrdApplyItem(models.Model):
    record = models.ForeignKey(AiPrdApplyRecord, on_delete=models.CASCADE, related_name="items")
    question = models.ForeignKey(
        "prds.PrdQuestion", on_delete=models.PROTECT, related_name="ai_prd_apply_items"
    )
    question_version_before = models.PositiveBigIntegerField()
    question_prompt = models.TextField()
    existing_answer = models.TextField(blank=True)
    integrated_answer = models.TextField()
    source_nodes = models.JSONField(default=list)
    preserved_existing_points = models.JSONField(default=list)
    added_points = models.JSONField(default=list)
    confidence = models.DecimalField(max_digits=5, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_prd_apply_items"
        ordering = ["question_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["record", "question"], name="uniq_ai_prd_apply_item_question"
            ),
            models.CheckConstraint(
                condition=Q(question_version_before__gte=1),
                name="ai_prd_apply_question_version_positive",
            ),
            models.CheckConstraint(
                condition=~Q(question_prompt=""), name="ai_prd_apply_question_not_blank"
            ),
            models.CheckConstraint(
                condition=Q(confidence__gte=Decimal("0")) & Q(confidence__lte=Decimal("1")),
                name="ai_prd_apply_confidence_range",
            ),
            models.CheckConstraint(
                condition=~Q(integrated_answer=""),
                name="ai_prd_apply_answer_not_blank",
            ),
        ]


class AiCoachChatLog(models.Model):
    """PRD 상세의 대화 조회(ai-chats)용 평면 기록. 한 행이 질문-답변 한 쌍이다.

    화면 말풍선의 원본은 이 표가 아니라 AiCoachMessage다.
    대화와 같은 30일이 지나면 delete_expired_chat_history가 지운다.
    """

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
    """코치 대화의 본체. 화면에 그려지는 말풍선 한 개가 이 행 하나다.

    AI PRD 충족도(PRD_EVALUATION)와는 무관하다. 충족도 결과는 AiJob에 담긴다.
    """

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
