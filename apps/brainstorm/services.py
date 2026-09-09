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
from apps.prds.models import Prd, PrdParticipant, PrdSection

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

    @staticmethod
    def enforce_create_note(access: PrdAccess) -> None:
        if access.role is None:
            raise PermissionDenied("Only a PRD participant can create a note.")
        role_permission_policy.enforce(
            access.role,
            ParticipantAction.BRAINSTORM_CREATE_NOTE,
            is_completed=access.prd.status == "completed",
        )

    @staticmethod
    def enforce_latest_canvas(canvas: BrainstormCanvas) -> None:
        latest_id = (
            BrainstormCanvas.objects.filter(prd_id=canvas.prd_id, is_deleted=False)
            .order_by("display_order", "-version_number", "-id")
            .values_list("id", flat=True)
            .first()
        )
        if canvas.is_deleted or latest_id != canvas.pk:
            raise PermissionDenied("이전 버전 보드는 조회만 할 수 있습니다.")

    def get_or_create_canvas(
        self,
        *,
        access: PrdAccess,
        context: IntegrationContext,
        idempotency_key: str,
    ) -> tuple[BrainstormCanvas, bool]:
        canvas = (
            BrainstormCanvas.objects.filter(prd=access.prd, is_deleted=False)
            .order_by("display_order", "-version_number", "-id")
            .first()
        )
        created = False
        if canvas is None:
            self.enforce_create_note(access)
            key = BrainstormMutationService._validate_idempotency_key(idempotency_key)
            try:
                canvas, created = BrainstormCanvas.objects.get_or_create(
                    prd=access.prd,
                    version_number=1,
                    defaults={
                        "creation_idempotency_key": key,
                        "created_by_user_id": context.user_id,
                        "display_order": 0,
                    },
                )
            except IntegrityError:
                canvas = BrainstormCanvas.objects.filter(prd=access.prd, is_deleted=False).first()
                created = False
        canvas.validate_context(context)
        return canvas, created

    @transaction.atomic
    def create_version(
        self,
        *,
        access: PrdAccess,
        context: IntegrationContext,
        source_canvas_id: int,
        idempotency_key: str,
    ) -> tuple[BrainstormCanvas, bool]:
        """Clone an existing board into the next PRD-wide version.

        Versions are independent editable boards. ``lineage_id`` is retained so
        contribution calculation can recognize the same idea across clones.
        """
        self.enforce_write(access)
        key = BrainstormMutationService._validate_idempotency_key(idempotency_key)
        Prd.objects.select_for_update().get(pk=access.prd.pk)

        existing = BrainstormCanvas.objects.filter(
            prd=access.prd,
            creation_idempotency_key=key,
            is_deleted=False,
        ).first()
        if existing is not None:
            existing.validate_context(context)
            return existing, False

        try:
            source = (
                BrainstormCanvas.objects.select_for_update()
                .select_related("prd")
                .get(pk=source_canvas_id, prd=access.prd, is_deleted=False)
            )
        except BrainstormCanvas.DoesNotExist as exc:
            raise ValidationError(
                {"source_canvas_id": "복제할 캔버스를 찾을 수 없습니다."}
            ) from exc
        source.validate_context(context)
        latest = (
            BrainstormCanvas.objects.select_for_update()
            .filter(prd=access.prd)
            .order_by("-version_number")
            .first()
        )
        next_version = (latest.version_number if latest else 0) + 1
        BrainstormCanvas.objects.filter(prd=access.prd, is_deleted=False).update(
            display_order=F("display_order") + 1
        )
        canvas = BrainstormCanvas.objects.create(
            prd=access.prd,
            version_number=next_version,
            source_canvas=source,
            created_by_user_id=context.user_id,
            creation_idempotency_key=key,
            display_order=0,
        )

        node_map = {}
        for node in source.nodes.filter(is_deleted=False).order_by("created_at", "id"):
            cloned = BrainstormNode.objects.create(
                canvas=canvas,
                lineage_id=node.lineage_id,
                node_type=node.node_type,
                content=node.content,
                color=node.color,
                position_x=node.position_x,
                position_y=node.position_y,
                section_id=node.section_id,
                held_from_section_id=node.held_from_section_id,
                author_id=node.author_id,
                assignee_id=node.assignee_id,
                status=node.status,
                introduced_in_version=node.introduced_in_version,
                version=1,
            )
            node_map[node.pk] = cloned
        for connection in source.connections.filter(is_deleted=False).order_by("created_at", "id"):
            node_a = node_map.get(connection.node_a_id)
            node_b = node_map.get(connection.node_b_id)
            if node_a is None or node_b is None:
                continue
            BrainstormConnection.objects.create(
                canvas=canvas,
                node_a=node_a,
                node_b=node_b,
                creation_idempotency_key=str(uuid.uuid4()),
                version=1,
            )
        source_viewport = source.user_viewports.filter(user_id=context.user_id).first()
        if source_viewport is not None:
            UserCanvasViewport.objects.create(
                canvas=canvas,
                user_id=context.user_id,
                viewport_x=source_viewport.viewport_x,
                viewport_y=source_viewport.viewport_y,
                zoom_level=source_viewport.zoom_level,
            )
        BrainstormChangeLog.objects.create(
            canvas=canvas,
            actor_user_id=context.user_id,
            action="canvas_version_created",
            target_type=BrainstormChangeTarget.CANVAS,
            target_id=str(canvas.pk),
            before_data={"source_canvas_id": source.pk, "source_version": source.version_number},
            after_data={"canvas_id": canvas.pk, "version_number": canvas.version_number},
        )
        return canvas, True

    @transaction.atomic
    def reorder_versions(
        self,
        *,
        access: PrdAccess,
        context: IntegrationContext,
        canvas_ids,
    ) -> tuple[BrainstormCanvas, ...]:
        self.enforce_write(access)
        Prd.objects.select_for_update().get(pk=access.prd.pk)
        rows = list(
            BrainstormCanvas.objects.select_for_update()
            .filter(prd=access.prd, is_deleted=False)
            .order_by("display_order", "-version_number", "-id")
        )
        if not isinstance(canvas_ids, list) or any(
            isinstance(value, bool) or not isinstance(value, int) for value in canvas_ids
        ):
            raise ValidationError({"canvas_ids": "활성 보드 ID 배열이 필요합니다."})
        if len(canvas_ids) != len(set(canvas_ids)) or set(canvas_ids) != {row.pk for row in rows}:
            raise ValidationError({"canvas_ids": "활성 보드 전체를 중복 없이 보내 주세요."})
        by_id = {row.pk: row for row in rows}
        ordered = [by_id[canvas_id] for canvas_id in canvas_ids]
        before = [row.pk for row in rows]
        for display_order, row in enumerate(ordered):
            row.display_order = display_order
        BrainstormCanvas.objects.bulk_update(ordered, ["display_order"])
        latest = ordered[0]
        BrainstormChangeLog.objects.bulk_create(
            [
                BrainstormChangeLog(
                    canvas=row,
                    actor_user_id=context.user_id,
                    action="canvas_versions_reordered",
                    target_type=BrainstormChangeTarget.CANVAS,
                    target_id=str(latest.pk),
                    before_data={"canvas_ids": before},
                    after_data={"canvas_ids": canvas_ids, "latest_canvas_id": latest.pk},
                )
                for row in ordered
            ]
        )
        return tuple(ordered)

    @transaction.atomic
    def delete_latest_version(
        self,
        *,
        access: PrdAccess,
        context: IntegrationContext,
        canvas_id: int,
    ) -> BrainstormCanvas:
        self.enforce_write(access)
        Prd.objects.select_for_update().get(pk=access.prd.pk)
        rows = list(
            BrainstormCanvas.objects.select_for_update()
            .filter(prd=access.prd, is_deleted=False)
            .order_by("display_order", "-version_number", "-id")
        )
        if not rows or rows[0].pk != canvas_id:
            raise ValidationError({"canvas_id": "현재 최신 보드만 삭제할 수 있습니다."})
        if len(rows) == 1:
            raise ValidationError({"canvas_id": "마지막 남은 보드는 삭제할 수 없습니다."})
        deleted = rows[0]
        deleted.is_deleted = True
        deleted.deleted_at = timezone.now()
        deleted.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
        remaining = rows[1:]
        for display_order, row in enumerate(remaining):
            row.display_order = display_order
        BrainstormCanvas.objects.bulk_update(remaining, ["display_order"])
        promoted = remaining[0]
        BrainstormChangeLog.objects.create(
            canvas=deleted,
            actor_user_id=context.user_id,
            action="canvas_version_deleted",
            target_type=BrainstormChangeTarget.CANVAS,
            target_id=str(deleted.pk),
            before_data={"is_deleted": False},
            after_data={
                "is_deleted": True,
                "promoted_canvas_id": promoted.pk,
            },
        )
        BrainstormChangeLog.objects.bulk_create(
            [
                BrainstormChangeLog(
                    canvas=row,
                    actor_user_id=context.user_id,
                    action="canvas_version_promoted",
                    target_type=BrainstormChangeTarget.CANVAS,
                    target_id=str(promoted.pk),
                    before_data={"deleted_canvas_id": deleted.pk},
                    after_data={"latest_canvas_id": promoted.pk},
                )
                for row in remaining
            ]
        )
        return promoted


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
    def _lock_canvas(
        canvas: BrainstormCanvas,
        *,
        access: PrdAccess | None = None,
        create_note: bool = False,
    ) -> BrainstormCanvas:
        if access is not None:
            try:
                prd = Prd.objects.select_for_update().get(pk=canvas.prd_id, is_deleted=False)
            except Prd.DoesNotExist as exc:
                raise PermissionDenied("The PRD is no longer available.") from exc
            current_access = PrdAccess(prd=prd, role=access.role, is_admin=access.is_admin)
            if create_note:
                BrainstormAccessService.enforce_create_note(current_access)
            else:
                BrainstormAccessService.enforce_write(current_access)
        locked = (
            BrainstormCanvas.objects.select_for_update().select_related("prd").get(pk=canvas.pk)
        )
        if access is not None:
            BrainstormAccessService.enforce_latest_canvas(locked)
        return locked

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
        canvas = self._lock_canvas(canvas, access=access)
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
        BrainstormAccessService.enforce_create_note(access)
        canvas = self._lock_canvas(canvas, access=access, create_note=True)
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
        canvas = self._lock_canvas(canvas, access=access)
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
        canvas = self._lock_canvas(canvas, access=access)
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
        canvas = self._lock_canvas(canvas, access=access)
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
            BrainstormNodeStatus.ACCEPTED if section is not None else BrainstormNodeStatus.DEFAULT
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

    @transaction.atomic
    def move_many(self, *, canvas, access, actor_user_id, payload):
        """Move selected notes as one all-or-nothing collaboration operation."""
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas, access=access)
        items = payload.get("nodes")
        if not isinstance(items, list) or not items or len(items) > 100:
            raise ValidationError({"nodes": "이동할 메모는 1개 이상 100개 이하여야 합니다."})
        submitted_ids = [str(item.get("id")) for item in items if isinstance(item, dict)]
        if len(submitted_ids) != len(items) or len(set(submitted_ids)) != len(items):
            raise ValidationError({"nodes": "메모 ID가 누락되었거나 중복되었습니다."})
        nodes = list(
            BrainstormNode.objects.select_for_update().filter(
                canvas=canvas,
                pk__in=submitted_ids,
                node_type=BrainstormNodeType.NOTE,
                is_deleted=False,
            )
        )
        nodes_by_id = {str(node.pk): node for node in nodes}
        if set(nodes_by_id) != set(submitted_ids):
            raise ValidationError({"nodes": "이동할 수 없는 메모가 포함되어 있습니다."})

        before_nodes = []
        after_nodes = []
        changed_at = timezone.now()
        for item in items:
            node = nodes_by_id[str(item["id"])]
            expected_version = self._validate_version(item.get("version"))
            if node.version != expected_version:
                raise VersionConflict(node)
            if node.status == BrainstormNodeStatus.HELD:
                raise ValidationError({"nodes": "보류 메모는 함께 이동할 수 없습니다."})
            section = self._section(canvas, item.get("section_id"))
            x = self._validate_coordinate(item.get("x"), "x")
            y = self._validate_coordinate(item.get("y"), "y")
            before_nodes.append(
                {
                    "id": str(node.pk),
                    "x": str(node.position_x),
                    "y": str(node.position_y),
                    "section_id": node.section_id,
                    "status": node.status,
                    "version": node.version,
                }
            )
            node.position_x = x
            node.position_y = y
            node.section = section
            node.status = (
                BrainstormNodeStatus.ACCEPTED
                if section is not None
                else BrainstormNodeStatus.DEFAULT
            )
            node.version += 1
            node.updated_at = changed_at
            after_nodes.append(
                {
                    "id": str(node.pk),
                    "x": str(x),
                    "y": str(y),
                    "section_id": node.section_id,
                    "status": node.status,
                    "version": node.version,
                }
            )
        BrainstormNode.objects.bulk_update(
            nodes,
            ["position_x", "position_y", "section", "status", "version", "updated_at"],
        )
        operation_id = uuid.uuid4()
        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="nodes_moved",
            target_type=BrainstormChangeTarget.CANVAS,
            target_id=canvas.pk,
            before={"nodes": before_nodes},
            after={"nodes": after_nodes},
            operation_id=operation_id,
        )
        return operation_id, nodes

    @transaction.atomic
    def undo_last(self, *, canvas, access, actor_user_id):
        """Undo the actor's latest still-current reversible canvas operation."""
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas, access=access)
        reversible = {
            "node_created",
            "node_content_updated",
            "node_assignee_updated",
            "node_moved",
            "nodes_moved",
            "auto_layout_applied",
            "node_status_updated",
            "node_deleted",
            "node_restored",
            "connection_created",
            "connection_deleted",
        }
        recent_desc = list(
            BrainstormChangeLog.objects.filter(canvas=canvas, actor_user_id=actor_user_id).order_by(
                "-id"
            )[:200]
        )
        recent = list(reversed(recent_desc))
        active = {str(row.operation_id): True for row in recent if row.action in reversible}
        expected_states = {}
        for row in recent:
            if row.action == "operation_undone":
                active[str(row.after_data.get("undone_operation_id"))] = False
            elif row.action == "operation_redone":
                operation_id = str(row.after_data.get("redone_operation_id"))
                active[operation_id] = True
                expected_states[operation_id] = row.after_data.get("state") or {}
        change = next(
            (
                row
                for row in recent_desc
                if row.action in reversible and active.get(str(row.operation_id), True)
            ),
            None,
        )
        if change is None:
            raise ValidationError({"undo": "실행 취소할 내 작업이 없습니다."})

        expected_state = expected_states.get(str(change.operation_id))
        if change.action in {"nodes_moved", "auto_layout_applied"}:
            self._undo_node_batch(
                canvas=canvas,
                change=change,
                expected_state=expected_state,
            )
        elif change.target_type == BrainstormChangeTarget.NODE:
            self._undo_node_change(
                canvas=canvas,
                change=change,
                expected_state=expected_state,
                actor_user_id=actor_user_id,
            )
        elif change.target_type == BrainstormChangeTarget.CONNECTION:
            self._undo_connection_change(
                canvas=canvas,
                change=change,
                expected_state=expected_state,
            )
        else:
            raise ValidationError({"undo": "현재 실행 취소할 수 없는 작업입니다."})

        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="operation_undone",
            target_type=BrainstormChangeTarget.CANVAS,
            target_id=canvas.pk,
            before={"action": change.action},
            after={
                "undone_operation_id": str(change.operation_id),
                "state": self._operation_state(canvas=canvas, change=change),
            },
        )
        return change

    @transaction.atomic
    def redo_last(self, *, canvas, access, actor_user_id):
        """Reapply the most recently undone operation unless new work cleared redo."""
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas, access=access)
        reversible = {
            "node_created",
            "node_content_updated",
            "node_assignee_updated",
            "node_moved",
            "nodes_moved",
            "auto_layout_applied",
            "node_status_updated",
            "node_deleted",
            "node_restored",
            "connection_created",
            "connection_deleted",
        }
        recent = list(
            BrainstormChangeLog.objects.filter(canvas=canvas, actor_user_id=actor_user_id).order_by(
                "-id"
            )[:200]
        )
        recent.reverse()
        originals = {str(row.operation_id): row for row in recent if row.action in reversible}
        active = {operation_id: True for operation_id in originals}
        undo_markers = {}
        for row in recent:
            if row.action == "operation_undone":
                operation_id = str(row.after_data.get("undone_operation_id"))
                if operation_id in originals:
                    active[operation_id] = False
                    undo_markers[operation_id] = row
            elif row.action == "operation_redone":
                operation_id = str(row.after_data.get("redone_operation_id"))
                if operation_id in originals:
                    active[operation_id] = True
        last_original_id = max((row.id for row in originals.values()), default=0)
        candidates = [
            marker
            for operation_id, marker in undo_markers.items()
            if not active.get(operation_id, True) and marker.id > last_original_id
        ]
        if not candidates:
            raise ValidationError({"redo": "다시 실행할 작업이 없습니다."})
        marker = max(candidates, key=lambda row: row.id)
        operation_id = str(marker.after_data["undone_operation_id"])
        change = originals[operation_id]
        expected_state = marker.after_data.get("state") or {}

        if change.action in {"nodes_moved", "auto_layout_applied"}:
            self._redo_node_batch(canvas=canvas, change=change, expected_state=expected_state)
        elif change.target_type == BrainstormChangeTarget.NODE:
            self._redo_node_change(
                canvas=canvas,
                change=change,
                expected_state=expected_state,
                actor_user_id=actor_user_id,
            )
        elif change.target_type == BrainstormChangeTarget.CONNECTION:
            self._redo_connection_change(
                canvas=canvas,
                change=change,
                expected_state=expected_state,
            )
        else:
            raise ValidationError({"redo": "현재 다시 실행할 수 없는 작업입니다."})

        self._record(
            canvas=canvas,
            actor_user_id=actor_user_id,
            action="operation_redone",
            target_type=BrainstormChangeTarget.CANVAS,
            target_id=canvas.pk,
            before={"action": change.action},
            after={
                "redone_operation_id": operation_id,
                "state": self._operation_state(canvas=canvas, change=change),
            },
        )
        return change

    @staticmethod
    def _operation_state(*, canvas, change):
        if change.action in {"nodes_moved", "auto_layout_applied"}:
            node_ids = [str(row.get("id")) for row in change.after_data.get("nodes", [])]
            return {
                "nodes": [
                    {
                        "id": str(row.pk),
                        "version": row.version,
                        "is_deleted": row.is_deleted,
                    }
                    for row in BrainstormNode.objects.filter(canvas=canvas, pk__in=node_ids)
                ]
            }
        if change.target_type == BrainstormChangeTarget.NODE:
            row = (
                BrainstormNode.objects.filter(canvas=canvas, pk=change.target_id)
                .values("version", "is_deleted")
                .first()
            )
            return {"version": row["version"], "is_deleted": row["is_deleted"]} if row else {}
        if change.target_type == BrainstormChangeTarget.CONNECTION:
            row = (
                BrainstormConnection.objects.filter(canvas=canvas, pk=change.target_id)
                .values("version", "is_deleted")
                .first()
            )
            return {"version": row["version"], "is_deleted": row["is_deleted"]} if row else {}
        return {}

    def _redo_node_batch(self, *, canvas, change, expected_state):
        after_rows = change.after_data.get("nodes") or []
        expected_versions = {
            str(row["id"]): row["version"] for row in expected_state.get("nodes", [])
        }
        nodes = list(
            BrainstormNode.objects.select_for_update().filter(
                canvas=canvas,
                pk__in=[str(row.get("id")) for row in after_rows],
                node_type=BrainstormNodeType.NOTE,
                is_deleted=False,
            )
        )
        if len(nodes) != len(after_rows):
            raise ValidationError({"redo": "일부 메모가 삭제되어 다시 실행할 수 없습니다."})
        after_by_id = {str(row["id"]): row for row in after_rows}
        changed_at = timezone.now()
        for node in nodes:
            if node.version != expected_versions.get(str(node.pk)):
                raise VersionConflict(node)
            after = after_by_id[str(node.pk)]
            section = self._section(canvas, after.get("section_id"))
            node.position_x = self._validate_coordinate(after.get("x"), "x")
            node.position_y = self._validate_coordinate(after.get("y"), "y")
            node.section = section
            node.status = (
                BrainstormNodeStatus.ACCEPTED
                if section is not None
                else BrainstormNodeStatus.DEFAULT
            )
            node.version += 1
            node.updated_at = changed_at
        BrainstormNode.objects.bulk_update(
            nodes,
            ["position_x", "position_y", "section", "status", "version", "updated_at"],
        )

    def _redo_node_change(self, *, canvas, change, expected_state, actor_user_id):
        try:
            node = BrainstormNode.objects.select_for_update().get(
                canvas=canvas, pk=change.target_id
            )
        except (BrainstormNode.DoesNotExist, ValidationError, ValueError) as exc:
            raise ValidationError({"redo": "대상 메모를 찾을 수 없습니다."}) from exc
        if node.version != expected_state.get("version"):
            raise VersionConflict(node)
        if change.action == "node_created":
            if not node.is_deleted:
                raise ValidationError({"redo": "메모가 이미 복원되어 있습니다."})
            node.restore()
            return
        if change.action == "node_deleted":
            if node.is_deleted:
                raise ValidationError({"redo": "메모가 이미 삭제되어 있습니다."})
            node.soft_delete()
            return
        if change.action == "node_restored":
            if not node.is_deleted:
                raise ValidationError({"redo": "메모 삭제 상태가 이미 변경되었습니다."})
            node.restore()
            return
        if node.is_deleted:
            raise ValidationError({"redo": "삭제된 메모의 작업은 다시 실행할 수 없습니다."})

        after = change.after_data
        if change.action == "node_content_updated":
            node.content = self._validate_content(after.get("content"))
            fields = ["content", "version", "updated_at"]
        elif change.action == "node_assignee_updated":
            node.assignee_id = after.get("assignee_id")
            fields = ["assignee_id", "version", "updated_at"]
        elif change.action == "node_moved":
            section = self._section(canvas, after.get("section_id"))
            node.position_x = self._validate_coordinate(after.get("x"), "x")
            node.position_y = self._validate_coordinate(after.get("y"), "y")
            node.section = section
            node.status = (
                BrainstormNodeStatus.ACCEPTED
                if section is not None
                else BrainstormNodeStatus.DEFAULT
            )
            fields = ["position_x", "position_y", "section", "status", "version", "updated_at"]
        elif change.action == "node_status_updated":
            after_status = after.get("status")
            section = self._section(canvas, after.get("section_id"))
            if after_status == BrainstormNodeStatus.HELD:
                node.hold(actor_user_id=actor_user_id)
                return
            node.section = section
            node.status = after_status
            node.held_from_section_id = after.get("held_from_section_id")
            fields = ["section", "status", "held_from_section", "version", "updated_at"]
        else:
            raise ValidationError({"redo": "현재 다시 실행할 수 없는 메모 작업입니다."})
        node.version += 1
        node.full_clean()
        node.save(update_fields=fields)

    def _redo_connection_change(self, *, canvas, change, expected_state):
        try:
            connection = (
                BrainstormConnection.objects.select_for_update()
                .select_related("node_a", "node_b")
                .get(canvas=canvas, pk=change.target_id)
            )
        except (BrainstormConnection.DoesNotExist, ValidationError, ValueError) as exc:
            raise ValidationError({"redo": "대상 연결선을 찾을 수 없습니다."}) from exc
        if connection.version != expected_state.get("version"):
            raise VersionConflict(connection)
        changed_at = timezone.now()
        if change.action == "connection_created":
            if (
                not connection.is_deleted
                or connection.node_a.is_deleted
                or connection.node_b.is_deleted
            ):
                raise ValidationError({"redo": "현재 연결선을 다시 만들 수 없습니다."})
            duplicate = (
                BrainstormConnection.objects.filter(canvas=canvas, is_deleted=False)
                .exclude(pk=connection.pk)
                .filter(
                    Q(node_a=connection.node_a, node_b=connection.node_b)
                    | Q(node_a=connection.node_b, node_b=connection.node_a)
                )
            )
            if duplicate.exists():
                raise ValidationError({"redo": "같은 메모 사이에 다른 연결선이 있습니다."})
            connection.is_deleted = False
            connection.deleted_at = None
        elif change.action == "connection_deleted":
            if connection.is_deleted:
                raise ValidationError({"redo": "연결선이 이미 삭제되어 있습니다."})
            connection.is_deleted = True
            connection.deleted_at = changed_at
        else:
            raise ValidationError({"redo": "현재 다시 실행할 수 없는 연결선 작업입니다."})
        connection.version += 1
        connection.updated_at = changed_at
        connection.save(update_fields=["is_deleted", "deleted_at", "version", "updated_at"])

    def _undo_node_batch(self, *, canvas, change, expected_state=None):
        before_rows = change.before_data.get("nodes") or []
        after_rows = change.after_data.get("nodes") or []
        if not before_rows or len(before_rows) != len(after_rows):
            raise ValidationError({"undo": "변경 전 위치 정보가 없어 취소할 수 없습니다."})
        before_by_id = {str(row.get("id")): row for row in before_rows}
        after_by_id = {str(row.get("id")): row for row in after_rows}
        expected_versions = {
            str(row["id"]): row["version"] for row in (expected_state or {}).get("nodes", [])
        }
        nodes = list(
            BrainstormNode.objects.select_for_update().filter(
                canvas=canvas,
                pk__in=before_by_id,
                node_type=BrainstormNodeType.NOTE,
                is_deleted=False,
            )
        )
        if len(nodes) != len(before_by_id):
            raise ValidationError({"undo": "일부 메모가 삭제되어 취소할 수 없습니다."})
        changed_at = timezone.now()
        for node in nodes:
            before = before_by_id[str(node.pk)]
            after = after_by_id.get(str(node.pk), {})
            expected = expected_versions.get(str(node.pk), after.get("version"))
            if node.version != expected:
                raise VersionConflict(node)
            section = self._section(canvas, before.get("section_id"))
            node.position_x = self._validate_coordinate(before.get("x"), "x")
            node.position_y = self._validate_coordinate(before.get("y"), "y")
            node.section = section
            node.status = (
                BrainstormNodeStatus.ACCEPTED
                if section is not None
                else BrainstormNodeStatus.DEFAULT
            )
            node.version += 1
            node.updated_at = changed_at
        BrainstormNode.objects.bulk_update(
            nodes,
            ["position_x", "position_y", "section", "status", "version", "updated_at"],
        )

    def _undo_node_change(self, *, canvas, change, expected_state=None, actor_user_id):
        try:
            node = BrainstormNode.objects.select_for_update().get(
                canvas=canvas, pk=change.target_id
            )
        except (BrainstormNode.DoesNotExist, ValidationError, ValueError) as exc:
            raise ValidationError({"undo": "대상 메모를 찾을 수 없습니다."}) from exc
        expected = (expected_state or {}).get("version", change.after_data.get("version"))
        if node.version != expected:
            raise VersionConflict(node)
        if change.action == "node_created":
            if node.is_deleted:
                raise ValidationError({"undo": "이미 삭제된 메모입니다."})
            if (
                BrainstormConnection.objects.filter(canvas=canvas, is_deleted=False)
                .filter(Q(node_a=node) | Q(node_b=node))
                .exists()
            ):
                raise ValidationError({"undo": "연결된 메모는 연결선을 먼저 취소해 주세요."})
            node.soft_delete()
            return
        if change.action == "node_deleted":
            if not node.is_deleted:
                raise ValidationError({"undo": "메모 삭제 상태가 이미 변경되었습니다."})
            node.restore()
            return
        if node.is_deleted:
            raise ValidationError({"undo": "삭제된 메모의 작업은 취소할 수 없습니다."})
        if change.action == "node_restored":
            node.soft_delete()
            return

        before = change.before_data
        if change.action == "node_content_updated":
            node.content = self._validate_content(before.get("content"))
            fields = ["content", "version", "updated_at"]
        elif change.action == "node_assignee_updated":
            node.assignee_id = before.get("assignee_id")
            fields = ["assignee_id", "version", "updated_at"]
        elif change.action == "node_moved":
            section = self._section(canvas, before.get("section_id"))
            node.position_x = self._validate_coordinate(before.get("x"), "x")
            node.position_y = self._validate_coordinate(before.get("y"), "y")
            node.section = section
            node.status = (
                BrainstormNodeStatus.ACCEPTED
                if section is not None
                else BrainstormNodeStatus.DEFAULT
            )
            fields = ["position_x", "position_y", "section", "status", "version", "updated_at"]
        elif change.action == "node_status_updated":
            before_status = before.get("status")
            section = self._section(canvas, before.get("section_id"))
            if before_status == BrainstormNodeStatus.HELD:
                if (
                    BrainstormConnection.objects.filter(canvas=canvas, is_deleted=False)
                    .filter(Q(node_a=node) | Q(node_b=node))
                    .exists()
                ):
                    raise ValidationError(
                        {"undo": "새 연결선이 있어 보류 복원을 취소할 수 없습니다."}
                    )
                section = None
            node.section = section
            node.status = before_status
            node.held_from_section_id = before.get("held_from_section_id")
            fields = ["section", "status", "held_from_section", "version", "updated_at"]
        else:
            raise ValidationError({"undo": "현재 실행 취소할 수 없는 메모 작업입니다."})
        node.version += 1
        node.full_clean()
        node.save(update_fields=fields)

    def _undo_connection_change(self, *, canvas, change, expected_state=None):
        try:
            connection = (
                BrainstormConnection.objects.select_for_update()
                .select_related("node_a", "node_b")
                .get(canvas=canvas, pk=change.target_id)
            )
        except (BrainstormConnection.DoesNotExist, ValidationError, ValueError) as exc:
            raise ValidationError({"undo": "대상 연결선을 찾을 수 없습니다."}) from exc
        expected = (expected_state or {}).get("version", change.after_data.get("version"))
        if connection.version != expected:
            raise VersionConflict(connection)
        changed_at = timezone.now()
        if change.action == "connection_created":
            if connection.is_deleted:
                raise ValidationError({"undo": "이미 삭제된 연결선입니다."})
            connection.is_deleted = True
            connection.deleted_at = changed_at
        elif change.action == "connection_deleted":
            if (
                not connection.is_deleted
                or connection.node_a.is_deleted
                or connection.node_b.is_deleted
            ):
                raise ValidationError({"undo": "현재 상태에서는 연결선을 복원할 수 없습니다."})
            duplicate = BrainstormConnection.objects.filter(canvas=canvas, is_deleted=False).filter(
                Q(node_a=connection.node_a, node_b=connection.node_b)
                | Q(node_a=connection.node_b, node_b=connection.node_a)
            )
            if duplicate.exists():
                raise ValidationError({"undo": "같은 메모 사이에 다른 연결선이 있습니다."})
            connection.is_deleted = False
            connection.deleted_at = None
        else:
            raise ValidationError({"undo": "현재 실행 취소할 수 없는 연결선 작업입니다."})
        connection.version += 1
        connection.updated_at = changed_at
        connection.save(update_fields=["is_deleted", "deleted_at", "version", "updated_at"])

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
        canvas = self._lock_canvas(canvas, access=access)
        node = self._lock_node(canvas=canvas, node_id=node_id, version=payload.get("version"))
        status = payload.get("status")
        if status not in BrainstormNodeStatus.values:
            raise ValidationError({"status": "메모 상태가 올바르지 않습니다."})
        before = {
            "status": node.status,
            "section_id": node.section_id,
            "held_from_section_id": node.held_from_section_id,
            "version": node.version,
        }
        if status == BrainstormNodeStatus.HELD:
            if node.status == BrainstormNodeStatus.HELD:
                raise ValidationError({"status": "이미 보류 중인 메모입니다."})
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
            origin_is_available = (
                node.held_from_section_id is not None
                and PrdSection.objects.filter(
                    pk=node.held_from_section_id,
                    prd=canvas.prd,
                    is_deleted=False,
                ).exists()
            )
            if origin_is_available:
                node.restore_from_hold()
            else:
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
            after={
                "status": node.status,
                "section_id": node.section_id,
                "held_from_section_id": node.held_from_section_id,
                "version": node.version,
            },
        )
        return node

    @transaction.atomic
    def delete_node(self, *, canvas, access, actor_user_id, node_id, version):
        BrainstormAccessService.enforce_write(access)
        canvas = self._lock_canvas(canvas, access=access)
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
        canvas = self._lock_canvas(canvas, access=access)
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
        canvas = self._lock_canvas(canvas, access=access)
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
        canvas = self._lock_canvas(canvas, access=access)
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
