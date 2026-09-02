from django.db import models
from django.db.models import Q


class AiFeatureType(models.TextChoices):
    COACHING = "COACHING", "AI 코칭"


class AiActionType(models.TextChoices):
    CHAT = "chat", "대화"
    DRAFT = "draft", "초안"


class AiUsageStatus(models.TextChoices):
    SUCCESS = "success", "성공"
    FAILED = "failed", "실패"
    CANCELLED = "cancelled", "취소"


class AiUsageLog(models.Model):
    prd = models.ForeignKey(
        "prds.Prd",
        on_delete=models.CASCADE,
        related_name="ai_usage_logs",
    )
    user_id = models.PositiveBigIntegerField()
    feature_type = models.CharField(max_length=32, choices=AiFeatureType.choices)
    action_type = models.CharField(max_length=32, choices=AiActionType.choices)
    status = models.CharField(max_length=16, choices=AiUsageStatus.choices)
    total_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_usage_logs"
        indexes = [
            models.Index(
                fields=["prd", "feature_type", "action_type", "status"],
                name="ai_usage_home_kpi_idx",
            )
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
                condition=Q(status__in=AiUsageStatus.values),
                name="ai_usage_status_valid",
            ),
        ]
