from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.integration.context import IntegrationContext
from apps.prds.models import Prd, PrdParticipant, PrdSection


class DatabaseRandomUUID(models.Func):
    """Use a database expression for UUID primary keys in PostgreSQL and tests."""

    function = "GEN_RANDOM_UUID"
    output_field = models.UUIDField()
    arity = 0

    def as_sqlite(self, compiler, connection, **extra_context):
        # SQLite stores UUIDField values as 32 hexadecimal characters.
        return "LOWER(HEX(RANDOMBLOB(16)))", []


class BrainstormNodeType(models.TextChoices):
    NOTE = "note", "일반 메모"
    TITLE = "title", "제목 카드"


class BrainstormNodeStatus(models.TextChoices):
    DEFAULT = "default", "기본"
    ACCEPTED = "accepted", "채택"
    HELD = "held", "보류"


class BrainstormChangeTarget(models.TextChoices):
    CANVAS = "canvas", "캔버스"
    NODE = "node", "노드"
    CONNECTION = "connection", "연결선"


class BrainstormCanvas(models.Model):
    prd = models.OneToOneField(
        Prd,
        on_delete=models.CASCADE,
        related_name="brainstorm_canvas",
    )
    creation_idempotency_key = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "brainstorm_canvases"

    def validate_context(self, context: IntegrationContext) -> None:
        """Validate the parent round/team boundary before canvas access or creation."""
        if self.prd.round_id is not None and self.prd.round_id != context.round_id:
            raise PermissionDenied("The canvas PRD belongs to another round.")
        if self.prd.team_id is not None and self.prd.team_id != context.team_id:
            raise PermissionDenied("The canvas PRD belongs to another current-round team.")


class BrainstormNode(models.Model):
    RESTORE_WINDOW_DAYS = 30

    id = models.UUIDField(primary_key=True, db_default=DatabaseRandomUUID(), editable=False)
    canvas = models.ForeignKey(
        BrainstormCanvas,
        on_delete=models.CASCADE,
        related_name="nodes",
    )
    node_type = models.CharField(
        max_length=16,
        choices=BrainstormNodeType.choices,
        default=BrainstormNodeType.NOTE,
    )
    content = models.TextField()
    creation_idempotency_key = models.CharField(max_length=128, blank=True, default="")
    color = models.CharField(max_length=32)
    position_x = models.DecimalField(max_digits=12, decimal_places=3)
    position_y = models.DecimalField(max_digits=12, decimal_places=3)
    section = models.ForeignKey(
        PrdSection,
        on_delete=models.SET_NULL,
        related_name="brainstorm_nodes",
        null=True,
        blank=True,
    )
    author_id = models.PositiveBigIntegerField(null=True, blank=True)
    assignee_id = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=BrainstormNodeStatus.choices,
        null=True,
        blank=True,
    )
    version = models.PositiveBigIntegerField(default=1)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "brainstorm_nodes"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["canvas", "is_deleted", "node_type", "status"],
                name="brain_node_canvas_state_idx",
            ),
            models.Index(
                fields=["canvas", "section", "is_deleted"],
                name="brain_node_section_idx",
            ),
            models.Index(
                fields=["canvas", "assignee_id", "is_deleted"],
                name="brain_node_assignee_idx",
            ),
            models.Index(fields=["deleted_at"], name="brain_node_deleted_at_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(node_type__in=BrainstormNodeType.values),
                name="brain_node_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__isnull=True) | Q(status__in=BrainstormNodeStatus.values),
                name="brain_node_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        node_type=BrainstormNodeType.NOTE,
                        author_id__isnull=False,
                        status__in=BrainstormNodeStatus.values,
                    )
                    | Q(
                        node_type=BrainstormNodeType.TITLE,
                        author_id__isnull=True,
                        assignee_id__isnull=True,
                        status__isnull=True,
                    )
                ),
                name="brain_node_type_fields_valid",
            ),
            models.CheckConstraint(
                condition=Q(author_id__isnull=True) | Q(author_id__gt=0),
                name="brain_node_author_positive",
            ),
            models.CheckConstraint(
                condition=Q(assignee_id__isnull=True) | Q(assignee_id__gt=0),
                name="brain_node_assignee_positive",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="brain_node_version_positive",
            ),
            models.CheckConstraint(
                condition=~Q(status=BrainstormNodeStatus.HELD) | Q(section__isnull=True),
                name="brain_held_node_unclassified",
            ),
            models.CheckConstraint(
                condition=~Q(content=""),
                name="brain_node_content_not_blank",
            ),
            models.UniqueConstraint(
                fields=["canvas", "author_id", "creation_idempotency_key"],
                condition=~Q(creation_idempotency_key=""),
                name="uniq_brain_node_request",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_deleted=False, deleted_at__isnull=True)
                    | Q(is_deleted=True, deleted_at__isnull=False)
                ),
                name="brain_node_deleted_consistent",
            ),
        ]

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}
        if self.section_id is not None and self.section.prd_id != self.canvas.prd_id:
            errors["section"] = "The section must belong to the canvas PRD."
        if (
            self.node_type == BrainstormNodeType.NOTE
            and self.assignee_id is not None
            and not PrdParticipant.objects.filter(
                prd_id=self.canvas.prd_id,
                user_id=self.assignee_id,
            ).exists()
        ):
            errors["assignee_id"] = "The assignee must be a PRD participant."
        if self.is_deleted != (self.deleted_at is not None):
            errors["deleted_at"] = "is_deleted and deleted_at must change together."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original_author_id = (
                type(self).objects.filter(pk=self.pk).values_list("author_id", flat=True).first()
            )
            if original_author_id != self.author_id:
                raise ValidationError({"author_id": "The node author cannot be changed."})
        super().save(*args, **kwargs)

    @classmethod
    def create_note(
        cls,
        *,
        canvas: BrainstormCanvas,
        context: IntegrationContext,
        content: str,
        color: str,
        position_x: Decimal,
        position_y: Decimal,
        creation_idempotency_key: str,
        section: PrdSection | None = None,
    ) -> BrainstormNode:
        canvas.validate_context(context)
        if not PrdParticipant.objects.filter(
            prd=canvas.prd,
            user_id=context.user_id,
        ).exists():
            raise PermissionDenied("The note author must be a PRD participant.")
        node = cls(
            canvas=canvas,
            node_type=BrainstormNodeType.NOTE,
            content=content,
            creation_idempotency_key=creation_idempotency_key,
            color=color,
            position_x=position_x,
            position_y=position_y,
            section=section,
            author_id=context.user_id,
            assignee_id=context.user_id,
            status=BrainstormNodeStatus.DEFAULT,
        )
        node.full_clean()
        node.save(force_insert=True)
        return node

    @transaction.atomic
    def soft_delete(self) -> None:
        if self.is_deleted:
            return
        deleted_at = timezone.now()
        BrainstormNode.objects.filter(pk=self.pk, is_deleted=False).update(
            is_deleted=True,
            deleted_at=deleted_at,
            version=F("version") + 1,
            updated_at=deleted_at,
        )
        BrainstormConnection.objects.filter(
            Q(node_a_id=self.pk) | Q(node_b_id=self.pk),
            canvas_id=self.canvas_id,
            is_deleted=False,
        ).update(
            is_deleted=True,
            deleted_at=deleted_at,
            version=F("version") + 1,
            updated_at=deleted_at,
        )
        self.refresh_from_db()

    @transaction.atomic
    def restore(self) -> None:
        if not self.is_deleted:
            return
        if self.deleted_at is None or self.deleted_at < timezone.now() - timedelta(
            days=self.RESTORE_WINDOW_DAYS
        ):
            raise ValidationError("The 30-day restore window has expired.")
        restored_at = timezone.now()
        BrainstormNode.objects.filter(pk=self.pk, is_deleted=True).update(
            is_deleted=False,
            deleted_at=None,
            version=F("version") + 1,
            updated_at=restored_at,
        )
        BrainstormConnection.objects.filter(
            Q(node_a_id=self.pk) | Q(node_b_id=self.pk),
            canvas_id=self.canvas_id,
            is_deleted=True,
            node_a__is_deleted=False,
            node_b__is_deleted=False,
        ).update(
            is_deleted=False,
            deleted_at=None,
            version=F("version") + 1,
            updated_at=restored_at,
        )
        self.refresh_from_db()

    @transaction.atomic
    def hold(self, *, actor_user_id: int) -> None:
        if self.node_type != BrainstormNodeType.NOTE:
            raise ValidationError("Only note nodes can be held.")
        if self.is_deleted:
            raise ValidationError("A deleted node cannot be held.")
        connections = list(
            BrainstormConnection.objects.filter(
                Q(node_a_id=self.pk) | Q(node_b_id=self.pk),
                canvas_id=self.canvas_id,
            )
        )
        for connection in connections:
            AuditLog.objects.create(
                canvas_id=self.canvas_id,
                actor_user_id=actor_user_id,
                action="connection_deleted",
                target_type=BrainstormChangeTarget.CONNECTION,
                target_id=str(connection.pk),
                reason="node_held",
                details={
                    "node_ids": [str(connection.node_a_id), str(connection.node_b_id)],
                },
            )
        BrainstormConnection.objects.filter(pk__in=[item.pk for item in connections]).delete()
        changed_at = timezone.now()
        BrainstormNode.objects.filter(pk=self.pk).update(
            status=BrainstormNodeStatus.HELD,
            section=None,
            version=F("version") + 1,
            updated_at=changed_at,
        )
        self.refresh_from_db()

    def restore_from_hold(self, *, position_x: Decimal, position_y: Decimal) -> None:
        if self.node_type != BrainstormNodeType.NOTE or self.status != BrainstormNodeStatus.HELD:
            raise ValidationError("Only held note nodes can be restored from hold.")
        changed_at = timezone.now()
        BrainstormNode.objects.filter(pk=self.pk).update(
            status=BrainstormNodeStatus.DEFAULT,
            section=None,
            position_x=position_x,
            position_y=position_y,
            version=F("version") + 1,
            updated_at=changed_at,
        )
        self.refresh_from_db()


class BrainstormConnection(models.Model):
    id = models.UUIDField(primary_key=True, db_default=DatabaseRandomUUID(), editable=False)
    canvas = models.ForeignKey(
        BrainstormCanvas,
        on_delete=models.CASCADE,
        related_name="connections",
    )
    node_a = models.ForeignKey(
        BrainstormNode,
        on_delete=models.CASCADE,
        related_name="connections_as_a",
    )
    node_b = models.ForeignKey(
        BrainstormNode,
        on_delete=models.CASCADE,
        related_name="connections_as_b",
    )
    creation_idempotency_key = models.CharField(
        max_length=128,
        default=uuid.uuid4,
        editable=False,
    )
    version = models.PositiveBigIntegerField(default=1)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "brainstorm_connections"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["canvas", "is_deleted", "updated_at"],
                name="brain_conn_poll_idx",
            ),
            models.Index(fields=["node_a", "is_deleted"], name="brain_conn_node_a_idx"),
            models.Index(fields=["node_b", "is_deleted"], name="brain_conn_node_b_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["canvas", "node_a", "node_b"],
                condition=Q(is_deleted=False),
                name="uniq_brain_connection_nodes",
            ),
            models.UniqueConstraint(
                fields=["canvas", "creation_idempotency_key"],
                name="uniq_brain_connection_request",
            ),
            models.CheckConstraint(
                condition=~Q(node_a=F("node_b")),
                name="brain_connection_not_self",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="brain_connection_version_positive",
            ),
            models.CheckConstraint(
                condition=~Q(creation_idempotency_key=""),
                name="brain_connection_key_not_blank",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_deleted=False, deleted_at__isnull=True)
                    | Q(is_deleted=True, deleted_at__isnull=False)
                ),
                name="brain_connection_deleted_consistent",
            ),
        ]

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}
        if self.node_a_id == self.node_b_id:
            errors["node_b"] = "A node cannot connect to itself."
        if self.node_a_id and self.node_a.canvas_id != self.canvas_id:
            errors["node_a"] = "Both nodes must belong to the connection canvas."
        if self.node_b_id and self.node_b.canvas_id != self.canvas_id:
            errors["node_b"] = "Both nodes must belong to the connection canvas."
        if not self.is_deleted and (
            (self.node_a_id and self.node_a.is_deleted)
            or (self.node_b_id and self.node_b.is_deleted)
        ):
            errors["is_deleted"] = "Deleted nodes cannot receive a connection."
        if self.is_deleted != (self.deleted_at is not None):
            errors["deleted_at"] = "is_deleted and deleted_at must change together."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if (
            self.node_a_id
            and self.node_b_id
            and uuid.UUID(str(self.node_a_id)).int > uuid.UUID(str(self.node_b_id)).int
        ):
            self.node_a_id, self.node_b_id = self.node_b_id, self.node_a_id
        super().save(*args, **kwargs)


class UserCanvasViewport(models.Model):
    canvas = models.ForeignKey(
        BrainstormCanvas,
        on_delete=models.CASCADE,
        related_name="user_viewports",
    )
    user_id = models.PositiveBigIntegerField()
    viewport_x = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    viewport_y = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    zoom_level = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.00"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "brainstorm_user_viewports"
        constraints = [
            models.UniqueConstraint(
                fields=["canvas", "user_id"],
                name="uniq_brain_viewport_user",
            ),
            models.CheckConstraint(
                condition=Q(user_id__gt=0),
                name="brain_viewport_user_positive",
            ),
            models.CheckConstraint(
                condition=Q(zoom_level__gte=Decimal("0.30")) & Q(zoom_level__lte=Decimal("2.00")),
                name="brain_viewport_zoom_range",
            ),
        ]


class BrainstormChangeLog(models.Model):
    canvas = models.ForeignKey(
        BrainstormCanvas,
        on_delete=models.CASCADE,
        related_name="change_logs",
    )
    actor_user_id = models.PositiveBigIntegerField()
    operation_id = models.UUIDField(default=uuid.uuid4, editable=False)
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=16, choices=BrainstormChangeTarget.choices)
    target_id = models.CharField(max_length=64)
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "brainstorm_change_logs"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["canvas", "-id"], name="brain_change_poll_idx"),
            models.Index(fields=["operation_id"], name="brain_change_operation_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(actor_user_id__gt=0),
                name="brain_change_actor_positive",
            ),
            models.CheckConstraint(
                condition=Q(target_type__in=BrainstormChangeTarget.values),
                name="brain_change_target_valid",
            ),
            models.CheckConstraint(
                condition=~Q(action=""),
                name="brain_change_action_not_blank",
            ),
            models.CheckConstraint(
                condition=~Q(target_id=""),
                name="brain_change_target_not_blank",
            ),
        ]


class AuditLog(models.Model):
    canvas = models.ForeignKey(
        BrainstormCanvas,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    actor_user_id = models.PositiveBigIntegerField()
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=16, choices=BrainstormChangeTarget.choices)
    target_id = models.CharField(max_length=64)
    reason = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "brainstorm_audit_logs"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["canvas", "-created_at"], name="brain_audit_created_idx"),
            models.Index(fields=["reason", "-created_at"], name="brain_audit_reason_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(actor_user_id__gt=0),
                name="brain_audit_actor_positive",
            ),
            models.CheckConstraint(
                condition=Q(target_type__in=BrainstormChangeTarget.values),
                name="brain_audit_target_valid",
            ),
            models.CheckConstraint(
                condition=~Q(action=""),
                name="brain_audit_action_not_blank",
            ),
            models.CheckConstraint(
                condition=~Q(target_id=""),
                name="brain_audit_target_not_blank",
            ),
        ]
