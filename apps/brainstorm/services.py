from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.accounts.permissions import ParticipantAction, role_permission_policy
from apps.integration.context import IntegrationContext
from apps.integration.repository import IntegrationRepository, get_default_integration_repository
from apps.prds.detail import PrdAccess, PrdAccessService
from apps.prds.models import PrdParticipant, PrdSection

from .models import (
    BrainstormCanvas,
    BrainstormChangeLog,
    BrainstormChangeTarget,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
    UserCanvasViewport,
)


@dataclass(slots=True)
class VersionConflict(Exception):
    latest: BrainstormNode | BrainstormConnection


@dataclass(slots=True)
class DuplicateConnection(Exception):
    connection: BrainstormConnection


@dataclass(slots=True)
class ConnectionSetConflict(Exception):
    latest: tuple[BrainstormConnection, ...]


class BrainstormAccessService:
    def get(self, *, prd_id: int, context: IntegrationContext) -> PrdAccess:
        access = PrdAccessService().get(prd_id=prd_id, context=context)
        return access

    @staticmethod
    def enforce_write(access: PrdAccess) -> None:
        if access.role is None:
            raise PermissionDenied("Only a PRD participant can edit the canvas.")
        role_permission_policy.enforce(
            access.role,
            ParticipantAction.EDIT,
            is_completed=access.prd.status == "completed",
        )

    def get_or_create_canvas(
        self,
        *,
        access: PrdAccess,
        context: IntegrationContext,
        idempotency_key: str,
    ) -> tuple[BrainstormCanvas, bool]:
        try:
            canvas = BrainstormCanvas.objects.get(prd=access.prd)
            created = False
        except BrainstormCanvas.DoesNotExist:
            self.enforce_write(access)
            key = BrainstormMutationService._validate_idempotency_key(idempotency_key)
            try:
                canvas, created = BrainstormCanvas.objects.get_or_create(
                    prd=access.prd,
                    defaults={"creation_idempotency_key": key},
                )
            except IntegrityError:
                canvas = BrainstormCanvas.objects.get(prd=access.prd)
                created = False
        canvas.validate_context(context)
        return canvas, created


class BrainstormMutationService:
    def __init__(self, repository: IntegrationRepository | None = None):
        self.repository = repository or get_default_integration_repository()

    @staticmethod
    def _validate_version(version) -> int:
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValidationError({"version": "version은 1 이상의 정수여야 합니다."})
        return version

    @staticmethod
    def _validate_idempotency_key(value) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError({"idempotency_key": "Idempotency-Key 헤더가 필요합니다."})
        normalized = value.strip()
        if len(normalized) > 128:
            raise ValidationError({"idempotency_key": "Idempotency-Key가 너무 깁니다."})
        return normalized

    @staticmethod
    def _validate_content(content) -> str:
        if not isinstance(content, str) or not content.strip():
            raise ValidationError({"content": "메모 내용을 입력해 주세요."})
        normalized = content.strip()
        if len(normalized) > settings.BRAINSTORM_NOTE_MAX_LENGTH:
            raise ValidationError(
                {
                    "content": (
                        f"메모 내용은 {settings.BRAINSTORM_NOTE_MAX_LENGTH}자 이하여야 합니다."
                    )
                }
            )
        return normalized

    @staticmethod
    def _validate_color(color) -> str:
        if not isinstance(color, str):
            raise ValidationError({"color": "색상 값이 올바르지 않습니다."})
        normalized = color.strip()
        if normalized not in settings.BRAINSTORM_ALLOWED_COLORS:
            raise ValidationError(
                {
                    "color": (
                        "허용된 색상을 사용해 주세요: "
                        + ", ".join(settings.BRAINSTORM_ALLOWED_COLORS)
                    )
                }
            )
        return normalized

    @staticmethod
    def _validate_coordinate(value, field_name) -> Decimal:
        if isinstance(value, bool):
            raise ValidationError({field_name: "좌표는 유효한 숫자여야 합니다."})
        try:
            coordinate = Decimal(str(value))
        except Exception as exc:
            raise ValidationError({field_name: "좌표는 유효한 숫자여야 합니다."}) from exc
        if not coordinate.is_finite() or coordinate.adjusted() > 8:
            raise ValidationError({field_name: "좌표 범위를 확인해 주세요."})
        return coordinate

    @staticmethod
    def _section(canvas: BrainstormCanvas, section_id) -> PrdSection | None:
        if section_id is None:
            return None
        if isinstance(section_id, bool) or not isinstance(section_id, int) or section_id < 1:
            raise ValidationError({"section_id": "section_id가 올바르지 않습니다."})
        try:
            return PrdSection.objects.get(
                pk=section_id,
                prd_id=canvas.prd_id,
                is_deleted=False,
            )
        except PrdSection.DoesNotExist as exc:
            raise ValidationError({"section_id": "현재 PRD의 활성 섹션이 아닙니다."}) from exc

    @staticmethod
    def _record(
        *,
        canvas,
        actor_user_id,
        action,
        target_type,
        target_id,
        before,
        after,
        operation_id=None,
    ) -> None:
        BrainstormChangeLog.objects.create(
            canvas=canvas,
            actor_user_id=actor_user_id,
            operation_id=operation_id or uuid.uuid4(),
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            before_data=before,
            after_data=after,
        )

    @staticmethod
    def _lock_canvas(canvas: BrainstormCanvas) -> BrainstormCanvas:
        return BrainstormCanvas.objects.select_for_update().select_related("prd").get(pk=canvas.pk)

    def _lock_node(
        self,
        *,
        canvas,
        node_id,
        version,
        include_deleted=False,
        require_note=True,
    ):
        expected = self._validate_version(version)
        try:
            # ``section`` is nullable.  Joining it here makes PostgreSQL reject
            # SELECT ... FOR UPDATE because the nullable side of an outer join
            # cannot be locked.  Lock only the node and its required relations;
            # Django can fetch section separately when a caller needs it.
            node = (
                BrainstormNode.objects.select_for_update()
                .select_related("canvas__prd")
                .get(pk=node_id, canvas=canvas)
            )
        except (BrainstormNode.DoesNotExist, ValidationError, ValueError) as exc:
            raise ValidationError({"node_id": "메모를 찾을 수 없습니다."}) from exc
        if require_note and node.node_type != BrainstormNodeType.NOTE:
            raise ValidationError({"node_id": "일반 메모만 변경할 수 있습니다."})
        if node.is_deleted and not include_deleted:
            raise ValidationError({"node_id": "삭제된 메모는 변경할 수 없습니다."})
        if node.version != expected:
            raise VersionConflict(node)
        return node

    @transaction.atomic
    def auto_layout(self, *, canvas, access, actor_user_id, payload):
        """Apply one complete layout operation or roll the whole batch back."""
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas)
        items = payload.get("nodes")
        if not isinstance(items, list) or not items:
            raise ValidationError({"nodes": "자동 정렬할 메모 배열이 필요합니다."})

        eligible_nodes = list(
            BrainstormNode.objects.select_for_update()
            .filter(
                canvas=canvas,
                node_type=BrainstormNodeType.NOTE,
                is_deleted=False,
            )
            .exclude(status=BrainstormNodeStatus.HELD)
            .order_by("id")
        )
        eligible_by_id = {str(node.pk): node for node in eligible_nodes}
        submitted_ids = [str(item.get("id")) for item in items if isinstance(item, dict)]
        if len(submitted_ids) != len(items) or len(set(submitted_ids)) != len(items):
            raise ValidationError({"nodes": "메모 ID가 누락되었거나 중복되었습니다."})
        if set(submitted_ids) != set(eligible_by_id):
            raise ValidationError(
                {"nodes": "삭제·보류·제목 카드를 제외한 활성 일반 메모 전체가 필요합니다."}
            )

        before_nodes = []
        after_nodes = []
        changed_at = timezone.now()
        for item in items:
            node = eligible_by_id[str(item["id"])]
            expected_version = self._validate_version(item.get("version"))
            if node.version != expected_version:
                raise VersionConflict(node)
            submitted_section_id = item.get("section_id")
            if submitted_section_id != node.section_id:
                raise ValidationError(
                    {"section_id": "자동 정렬은 메모의 기존 섹션 분류를 변경할 수 없습니다."}
                )
            x = self._validate_coordinate(item.get("x"), "x")
            y = self._validate_coordinate(item.get("y"), "y")
            before_nodes.append(
                {
                    "id": str(node.pk),
                    "x": str(node.position_x),
                    "y": str(node.position_y),
                    "section_id": node.section_id,
                    "version": node.version,
                }
            )
            node.position_x = x
            node.position_y = y
            node.version += 1
            node.updated_at = changed_at
            after_nodes.append(
                {
                    "id": str(node.pk),
                    "x": str(x),
                    "y": str(y),
                    "section_id": node.section_id,
                    "version": node.version,
                }
            )

        BrainstormNode.objects.bulk_update(
            eligible_nodes,
            ["position_x", "position_y", "version", "updated_at"],
        )
        operation_id = uuid.uuid4()
        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="auto_layout_applied",
            target_type=BrainstormChangeTarget.CANVAS,
            target_id=canvas.pk,
            before={"nodes": before_nodes},
            after={"nodes": after_nodes},
            operation_id=operation_id,
        )
        return operation_id, eligible_nodes

    @transaction.atomic
    def create_note(self, *, canvas, access, context, payload, idempotency_key):
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas)
        key = self._validate_idempotency_key(idempotency_key)
        content = self._validate_content(payload.get("content"))
        color = self._validate_color(payload.get("color"))
        position_x = self._validate_coordinate(payload.get("x"), "x")
        position_y = self._validate_coordinate(payload.get("y"), "y")
        section = self._section(canvas, payload.get("section_id"))
        existing = BrainstormNode.objects.filter(
            canvas=canvas,
            author_id=context.user_id,
            creation_idempotency_key=key,
        ).first()
        if existing:
            requested = (content, color, position_x, position_y, section.pk if section else None)
            stored = (
                existing.content,
                existing.color,
                existing.position_x,
                existing.position_y,
                existing.section_id,
            )
            if requested != stored:
                raise ValidationError(
                    {"idempotency_key": "같은 키가 다른 메모 생성 요청에 사용되었습니다."}
                )
            return existing, False
        node = BrainstormNode.create_note(
            canvas=canvas,
            context=context,
            content=content,
            color=color,
            position_x=position_x,
            position_y=position_y,
            section=section,
            creation_idempotency_key=key,
        )
        self._record(
            canvas=canvas,
            actor_user_id=context.user_id,
            action="node_created",
            target_type=BrainstormChangeTarget.NODE,
            target_id=node.pk,
            before={},
            after={"version": node.version},
        )
        return node, True

    @transaction.atomic
    def update_content(self, *, canvas, access, actor_user_id, node_id, payload):
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas)
        node = self._lock_node(canvas=canvas, node_id=node_id, version=payload.get("version"))
        before = {"content": node.content, "version": node.version}
        node.content = self._validate_content(payload.get("content"))
        node.version += 1
        node.save(update_fields=["content", "version", "updated_at"])
        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="node_content_updated",
            target_type=BrainstormChangeTarget.NODE,
            target_id=node.pk,
            before=before,
            after={"content": node.content, "version": node.version},
        )
        return node

    @transaction.atomic
    def assign(self, *, canvas, access, actor_user_id, node_id, payload):
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas)
        node = self._lock_node(canvas=canvas, node_id=node_id, version=payload.get("version"))
        assignee_id = payload.get("assignee_id")
        if assignee_id is not None and (
            isinstance(assignee_id, bool) or not isinstance(assignee_id, int) or assignee_id < 1
        ):
            raise ValidationError({"assignee_id": "담당자 ID가 올바르지 않습니다."})
        if assignee_id is not None:
            participant_exists = PrdParticipant.objects.filter(
                prd=access.prd,
                user_id=assignee_id,
            ).exists()
            membership = self.repository.get_active_membership(assignee_id, access.prd.round_id)
            if not participant_exists or membership is None:
                raise ValidationError({"assignee_id": "현재 회차의 PRD 참여자가 아닙니다."})
        before = {"assignee_id": node.assignee_id, "version": node.version}
        node.assignee_id = assignee_id
        node.version += 1
        node.full_clean()
        node.save(update_fields=["assignee_id", "version", "updated_at"])
        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="node_assignee_updated",
            target_type=BrainstormChangeTarget.NODE,
            target_id=node.pk,
            before=before,
            after={"assignee_id": node.assignee_id, "version": node.version},
        )
        return node

    @transaction.atomic
    def move(self, *, canvas, access, actor_user_id, node_id, payload):
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas)
        node = self._lock_node(canvas=canvas, node_id=node_id, version=payload.get("version"))
        if node.status == BrainstormNodeStatus.HELD:
            raise ValidationError({"status": "보류 메모는 이동할 수 없습니다."})
        section = self._section(canvas, payload.get("section_id"))
        x = self._validate_coordinate(payload.get("x"), "x")
        y = self._validate_coordinate(payload.get("y"), "y")
        before = {
            "x": str(node.position_x),
            "y": str(node.position_y),
            "section_id": node.section_id,
            "status": node.status,
            "version": node.version,
        }
        node.position_x = x
        node.position_y = y
        node.section = section
        node.status = (
            BrainstormNodeStatus.ACCEPTED
            if section is not None
            else BrainstormNodeStatus.DEFAULT
        )
        node.version += 1
        node.save(
            update_fields=[
                "position_x",
                "position_y",
                "section",
                "status",
                "version",
                "updated_at",
            ]
        )
        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="node_moved",
            target_type=BrainstormChangeTarget.NODE,
            target_id=node.pk,
            before=before,
            after={
                "x": str(x),
                "y": str(y),
                "section_id": node.section_id,
                "status": node.status,
                "version": node.version,
            },
        )
        return node

    @staticmethod
    def _unclassified_restore_position(canvas, *, exclude_node_id):
        used = {
            (node.position_x, node.position_y)
            for node in BrainstormNode.objects.filter(
                canvas=canvas,
                node_type=BrainstormNodeType.NOTE,
                section__isnull=True,
                is_deleted=False,
            )
            .exclude(status=BrainstormNodeStatus.HELD)
            .exclude(pk=exclude_node_id)
            .only("position_x", "position_y")
        }
        for index in range(len(used) + 1):
            candidate = (
                Decimal(40 + (index % 8) * 36),
                Decimal(40 + (index // 8) * 36),
            )
            if candidate not in used:
                return candidate
        raise RuntimeError("Could not allocate an unclassified restore position.")

    @transaction.atomic
    def change_status(self, *, canvas, access, actor_user_id, node_id, payload):
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas)
        node = self._lock_node(canvas=canvas, node_id=node_id, version=payload.get("version"))
        status = payload.get("status")
        if status not in BrainstormNodeStatus.values:
            raise ValidationError({"status": "메모 상태가 올바르지 않습니다."})
        before = {"status": node.status, "section_id": node.section_id, "version": node.version}
        if status == BrainstormNodeStatus.HELD:
            expected_connections = payload.get("connection_versions")
            if not isinstance(expected_connections, list):
                raise ValidationError(
                    {"connection_versions": "보류할 메모의 연결선 버전 배열이 필요합니다."}
                )
            submitted = {}
            for item in expected_connections:
                if not isinstance(item, dict):
                    raise ValidationError(
                        {"connection_versions": "연결선 ID와 version이 필요합니다."}
                    )
                connection_id = str(item.get("id", ""))
                if not connection_id or connection_id in submitted:
                    raise ValidationError(
                        {"connection_versions": "연결선 ID가 누락되었거나 중복되었습니다."}
                    )
                submitted[connection_id] = self._validate_version(item.get("version"))
            current_connections = tuple(
                BrainstormConnection.objects.select_for_update()
                .filter(
                    Q(node_a=node) | Q(node_b=node),
                    canvas=canvas,
                    is_deleted=False,
                )
                .order_by("id")
            )
            current = {str(connection.pk): connection.version for connection in current_connections}
            if submitted != current:
                raise ConnectionSetConflict(current_connections)
            node.hold(actor_user_id=actor_user_id)
        elif node.status == BrainstormNodeStatus.HELD:
            if status != BrainstormNodeStatus.DEFAULT:
                raise ValidationError({"status": "보류 메모는 기본 상태로만 복원할 수 있습니다."})
            x, y = self._unclassified_restore_position(canvas, exclude_node_id=node.pk)
            node.restore_from_hold(position_x=x, position_y=y)
        else:
            raise ValidationError(
                {"status": "채택 여부는 메모의 섹션 위치에 따라 자동으로 결정됩니다."}
            )
        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="node_status_updated",
            target_type=BrainstormChangeTarget.NODE,
            target_id=node.pk,
            before=before,
            after={"status": node.status, "section_id": node.section_id, "version": node.version},
        )
        return node

    @transaction.atomic
    def delete_node(self, *, canvas, access, actor_user_id, node_id, version):
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas)
        node = self._lock_node(canvas=canvas, node_id=node_id, version=version)
        before = {"is_deleted": False, "version": node.version}
        node.soft_delete()
        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="node_deleted",
            target_type=BrainstormChangeTarget.NODE,
            target_id=node.pk,
            before=before,
            after={"is_deleted": True, "version": node.version},
        )
        return node

    @transaction.atomic
    def restore_node(self, *, canvas, access, actor_user_id, node_id, version):
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas)
        node = self._lock_node(
            canvas=canvas,
            node_id=node_id,
            version=version,
            include_deleted=True,
        )
        if not node.is_deleted:
            raise ValidationError({"node_id": "삭제된 메모가 아닙니다."})
        before = {"is_deleted": True, "version": node.version}
        node.restore()
        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="node_restored",
            target_type=BrainstormChangeTarget.NODE,
            target_id=node.pk,
            before=before,
            after={"is_deleted": False, "version": node.version},
        )
        return node

    @transaction.atomic
    def create_connection(self, *, canvas, access, actor_user_id, payload, idempotency_key):
        BrainstormAccessService.enforce_write(access)
        key = self._validate_idempotency_key(idempotency_key)
        canvas = self._lock_canvas(canvas)
        existing_request = BrainstormConnection.objects.filter(
            canvas=canvas,
            creation_idempotency_key=key,
        ).first()
        if existing_request:
            requested_ids = {str(payload.get("node_a_id")), str(payload.get("node_b_id"))}
            existing_ids = {str(existing_request.node_a_id), str(existing_request.node_b_id)}
            if requested_ids != existing_ids:
                raise ValidationError(
                    {"idempotency_key": "같은 키가 다른 연결 요청에 사용되었습니다."}
                )
            return existing_request, False
        node_a = self._lock_node(
            canvas=canvas,
            node_id=payload.get("node_a_id"),
            version=payload.get("node_a_version"),
            require_note=False,
        )
        node_b = self._lock_node(
            canvas=canvas,
            node_id=payload.get("node_b_id"),
            version=payload.get("node_b_version"),
            require_note=False,
        )
        if node_a.pk == node_b.pk:
            raise ValidationError({"node_b_id": "자기 자신과 연결할 수 없습니다."})
        duplicate = (
            BrainstormConnection.objects.filter(
                canvas=canvas,
                is_deleted=False,
            )
            .filter(Q(node_a=node_a, node_b=node_b) | Q(node_a=node_b, node_b=node_a))
            .first()
        )
        if duplicate:
            raise DuplicateConnection(duplicate)
        connection = BrainstormConnection(
            canvas=canvas,
            node_a=node_a,
            node_b=node_b,
            creation_idempotency_key=key,
        )
        connection.full_clean()
        connection.save(force_insert=True)
        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="connection_created",
            target_type=BrainstormChangeTarget.CONNECTION,
            target_id=connection.pk,
            before={},
            after={"version": connection.version},
        )
        return connection, True

    @transaction.atomic
    def delete_connection(self, *, canvas, access, actor_user_id, connection_id, version):
        BrainstormAccessService.enforce_write(access)
        expected = self._validate_version(version)
        canvas = self._lock_canvas(canvas)
        try:
            connection = BrainstormConnection.objects.select_for_update().get(
                pk=connection_id,
                canvas=canvas,
                is_deleted=False,
            )
        except (BrainstormConnection.DoesNotExist, ValidationError, ValueError) as exc:
            raise ValidationError({"connection_id": "연결선을 찾을 수 없습니다."}) from exc
        if connection.version != expected:
            raise VersionConflict(connection)
        before = {"is_deleted": False, "version": connection.version}
        changed_at = timezone.now()
        BrainstormConnection.objects.filter(pk=connection.pk).update(
            is_deleted=True,
            deleted_at=changed_at,
            version=F("version") + 1,
            updated_at=changed_at,
        )
        connection.refresh_from_db()
        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="connection_deleted",
            target_type=BrainstormChangeTarget.CONNECTION,
            target_id=connection.pk,
            before=before,
            after={"is_deleted": True, "version": connection.version},
        )
        return connection

    @transaction.atomic
    def save_viewport(self, *, canvas, user_id, payload):
        canvas = self._lock_canvas(canvas)
        zoom = self._validate_coordinate(payload.get("zoom_level"), "zoom_level")
        if not Decimal("0.30") <= zoom <= Decimal("2.00"):
            raise ValidationError({"zoom_level": "확대 비율은 0.30부터 2.00까지입니다."})
        viewport, _ = UserCanvasViewport.objects.update_or_create(
            canvas=canvas,
            user_id=user_id,
            defaults={
                "viewport_x": self._validate_coordinate(payload.get("viewport_x"), "viewport_x"),
                "viewport_y": self._validate_coordinate(payload.get("viewport_y"), "viewport_y"),
                "zoom_level": zoom,
            },
        )
        viewport.full_clean()
        return viewport


class BrainstormEventPublisher:
    """Handoff point for later PRD-apply code without coupling it to polling views."""

    @staticmethod
    def prd_apply_completed(*, canvas, actor_user_id, application_id, details=None):
        return BrainstormChangeLog.objects.create(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="prd_apply_completed",
            target_type=BrainstormChangeTarget.CANVAS,
            target_id=str(canvas.pk),
            before_data={},
            after_data={**(details or {}), "application_id": str(application_id)},
        )
