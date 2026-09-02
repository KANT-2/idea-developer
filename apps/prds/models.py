from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import (
    Case,
    CharField,
    Count,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Cast, Round


class PrdType(models.TextChoices):
    NEW_PRODUCT = "new_product", "신규 프로젝트"
    NEW_FEATURE = "new_feature", "신규 기능"
    IMPROVEMENT = "improvement", "기능 개선"


class PrdStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "작성 중"
    COMPLETED = "completed", "완료"
    HELD = "held", "보류"
    DROPPED = "dropped", "드랍"


class PrdParticipantRole(models.TextChoices):
    OWNER = "owner", "소유자"
    EDITOR = "editor", "편집자"
    TUTOR = "tutor", "튜터"
    VIEWER = "viewer", "열람자"


class PrdQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_deleted=False)

    def with_completion_rate(self):
        """Annotate the single completion value used by cards, details, and KPI queries."""
        queryset = self.annotate(
            active_question_count=Count(
                "sections__questions",
                filter=Q(
                    sections__is_deleted=False,
                    sections__questions__is_deleted=False,
                ),
                distinct=True,
            ),
            completed_question_count=Count(
                "sections__questions",
                filter=Q(
                    sections__is_deleted=False,
                    sections__questions__is_deleted=False,
                    sections__questions__is_completed=True,
                ),
                distinct=True,
            ),
        )
        return queryset.annotate(
            completion_rate=Case(
                When(active_question_count=0, then=Value(0)),
                default=Cast(
                    Round(
                        F("completed_question_count") * Value(100.0) / F("active_question_count")
                    ),
                    IntegerField(),
                ),
                output_field=IntegerField(),
            )
        )

    def accessible_home(self, *, user_id: int, round_id: int, team_id: int):
        participant_access = PrdParticipant.objects.filter(
            prd_id=OuterRef("pk"),
            user_id=user_id,
        )
        return (
            self.active()
            .filter(round_id=round_id)
            .annotate(_is_participant=Exists(participant_access))
            .filter(
                Q(creator_user_id=user_id)
                | Q(_is_participant=True)
                | Q(is_team_shared=True, team_id=team_id)
            )
        )

    def with_home_metrics(self, *, user_id: int):
        my_role = PrdParticipant.objects.filter(
            prd_id=OuterRef("pk"),
            user_id=user_id,
        ).values("role")[:1]
        return self.with_completion_rate().annotate(
            participant_count=Count("participants", distinct=True),
            ai_coaching_count=Count(
                "ai_usage_logs",
                filter=Q(
                    ai_usage_logs__feature_type="COACHING",
                    ai_usage_logs__action_type="chat",
                    ai_usage_logs__status="success",
                ),
                distinct=True,
            ),
            my_role=Subquery(my_role, output_field=CharField()),
        )


class PrdTemplate(models.Model):
    """One confirmed template definition for each PRD type."""

    prd_type = models.CharField(max_length=32, choices=PrdType.choices, unique=True)
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "prd_templates"
        ordering = ["prd_type"]
        constraints = [
            models.CheckConstraint(
                condition=Q(prd_type__in=PrdType.values),
                name="prd_template_type_valid",
            )
        ]


class PrdTemplateSection(models.Model):
    template = models.ForeignKey(
        PrdTemplate,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    title = models.CharField(max_length=200)
    guide = models.TextField(blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        db_table = "prd_template_sections"
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "position"],
                name="uniq_prd_template_section_position",
            )
        ]


class PrdTemplateQuestion(models.Model):
    section = models.ForeignKey(
        PrdTemplateSection,
        on_delete=models.CASCADE,
        related_name="questions",
    )
    prompt = models.TextField()
    position = models.PositiveIntegerField()

    class Meta:
        db_table = "prd_template_questions"
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "position"],
                name="uniq_prd_template_question_position",
            )
        ]


class Prd(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    deadline = models.DateField(null=True, blank=True)
    prd_type = models.CharField(max_length=32, choices=PrdType.choices)
    status = models.CharField(
        max_length=32,
        choices=PrdStatus.choices,
        default=PrdStatus.IN_PROGRESS,
    )
    round_id = models.PositiveBigIntegerField()
    team_id = models.PositiveBigIntegerField(null=True, blank=True)
    is_team_shared = models.BooleanField(default=False)
    creator_user_id = models.PositiveBigIntegerField()
    creation_idempotency_key = models.CharField(max_length=128)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PrdQuerySet.as_manager()

    class Meta:
        db_table = "prds"
        indexes = [
            models.Index(fields=["status", "-updated_at"], name="prd_status_updated_idx"),
            models.Index(fields=["prd_type", "-updated_at"], name="prd_type_updated_idx"),
            models.Index(fields=["deadline"], name="prd_deadline_idx"),
            models.Index(fields=["round_id", "team_id"], name="prd_round_team_idx"),
            models.Index(
                fields=["round_id", "team_id", "is_team_shared"],
                name="prd_team_shared_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(prd_type__in=PrdType.values),
                name="prd_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=PrdStatus.values),
                name="prd_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(round_id__gt=0),
                name="prd_round_id_positive",
            ),
            models.CheckConstraint(
                condition=Q(creator_user_id__gt=0),
                name="prd_creator_user_id_positive",
            ),
            models.CheckConstraint(
                condition=Q(team_id__isnull=True) | Q(team_id__gt=0),
                name="prd_team_id_null_or_positive",
            ),
            models.CheckConstraint(
                condition=~Q(creation_idempotency_key=""),
                name="prd_idempotency_key_not_blank",
            ),
            models.UniqueConstraint(
                fields=["creator_user_id", "round_id", "creation_idempotency_key"],
                name="uniq_prd_creation_request",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_deleted=False, deleted_at__isnull=True)
                    | Q(is_deleted=True, deleted_at__isnull=False)
                ),
                name="prd_deleted_fields_consistent",
            ),
        ]

    @staticmethod
    def completion_rate_from_counts(*, completed: int, total: int) -> int:
        if total <= 0:
            return 0
        value = (Decimal(completed) * Decimal(100) / Decimal(total)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        return max(0, min(100, int(value)))

    def calculate_completion_rate(self) -> int:
        questions = PrdQuestion.objects.filter(
            section__prd=self,
            section__is_deleted=False,
            is_deleted=False,
        )
        counts = questions.aggregate(
            total=Count("id"),
            completed=Count("id", filter=Q(is_completed=True)),
        )
        return self.completion_rate_from_counts(
            completed=counts["completed"], total=counts["total"]
        )

    def clean(self):
        super().clean()
        if self.is_deleted != (self.deleted_at is not None):
            raise ValidationError({"deleted_at": "is_deleted and deleted_at must change together."})


class PrdParticipant(models.Model):
    prd = models.ForeignKey(Prd, on_delete=models.CASCADE, related_name="participants")
    user_id = models.PositiveBigIntegerField()
    participant_id = models.PositiveBigIntegerField()
    role = models.CharField(max_length=16, choices=PrdParticipantRole.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prd_participants"
        constraints = [
            models.CheckConstraint(
                condition=Q(user_id__gt=0),
                name="prd_participant_user_id_positive",
            ),
            models.CheckConstraint(
                condition=Q(participant_id__gt=0),
                name="prd_participant_external_id_positive",
            ),
            models.CheckConstraint(
                condition=Q(role__in=PrdParticipantRole.values),
                name="prd_participant_role_valid",
            ),
            models.UniqueConstraint(fields=["prd", "user_id"], name="uniq_prd_participant_user"),
            models.UniqueConstraint(
                fields=["prd", "participant_id"], name="uniq_prd_participant_external"
            ),
        ]
        indexes = [
            models.Index(fields=["user_id", "prd"], name="prd_part_user_prd_idx"),
        ]


class PrdSection(models.Model):
    prd = models.ForeignKey(Prd, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=200)
    guide = models.TextField(blank=True)
    position = models.PositiveIntegerField()
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "prd_sections"
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["prd", "position"], name="uniq_prd_section_position"),
            models.CheckConstraint(
                condition=(
                    Q(is_deleted=False, deleted_at__isnull=True)
                    | Q(is_deleted=True, deleted_at__isnull=False)
                ),
                name="prd_section_deleted_fields_consistent",
            ),
        ]


class PrdQuestion(models.Model):
    section = models.ForeignKey(PrdSection, on_delete=models.CASCADE, related_name="questions")
    prompt = models.TextField()
    position = models.PositiveIntegerField()
    is_completed = models.BooleanField(default=False)
    version = models.PositiveBigIntegerField(default=1)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "prd_questions"
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "position"], name="uniq_prd_question_position"
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_deleted=False, deleted_at__isnull=True)
                    | Q(is_deleted=True, deleted_at__isnull=False)
                ),
                name="prd_question_deleted_fields_consistent",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="prd_question_version_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=["section", "is_deleted", "is_completed"],
                name="prd_question_completion_idx",
            )
        ]


class PrdAnswer(models.Model):
    question = models.OneToOneField(
        PrdQuestion,
        on_delete=models.CASCADE,
        related_name="answer",
    )
    content = models.TextField(blank=True)
    updated_by_user_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "prd_answers"


class PrdChangeHistory(models.Model):
    prd = models.ForeignKey(Prd, on_delete=models.CASCADE, related_name="change_history")
    actor_user_id = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=64)
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prd_change_history"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["prd", "-created_at"], name="prd_history_created_idx")]


class PrdCommentType(models.TextChoices):
    GENERAL = "general", "일반"
    GUIDANCE = "guidance", "지도"
    REVIEW = "review", "리뷰"
    POST_COMPLETION_REVIEW = "post_completion_review", "완료 후 리뷰"


class PrdComment(models.Model):
    prd = models.ForeignKey(Prd, on_delete=models.CASCADE, related_name="comments")
    section_question = models.ForeignKey(
        PrdQuestion,
        on_delete=models.SET_NULL,
        related_name="comments",
        null=True,
        blank=True,
    )
    author_user_id = models.PositiveBigIntegerField()
    author_role_at_created = models.CharField(
        max_length=16,
        choices=PrdParticipantRole.choices,
    )
    comment_type = models.CharField(max_length=32, choices=PrdCommentType.choices)
    content = models.TextField()
    is_contribution_eligible = models.BooleanField()
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "prd_comments"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["prd", "is_deleted", "-created_at"],
                name="prd_comment_list_idx",
            ),
            models.Index(
                fields=["prd", "section_question", "is_deleted"],
                name="prd_comment_question_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(author_user_id__gt=0),
                name="prd_comment_author_positive",
            ),
            models.CheckConstraint(
                condition=Q(author_role_at_created__in=PrdParticipantRole.values),
                name="prd_comment_author_role_valid",
            ),
            models.CheckConstraint(
                condition=Q(comment_type__in=PrdCommentType.values),
                name="prd_comment_type_valid",
            ),
            models.CheckConstraint(
                condition=~Q(content=""),
                name="prd_comment_content_not_blank",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_deleted=False, deleted_at__isnull=True)
                    | Q(is_deleted=True, deleted_at__isnull=False)
                ),
                name="prd_comment_deleted_consistent",
            ),
        ]
