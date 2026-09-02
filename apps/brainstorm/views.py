from __future__ import annotations

import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.permissions import ParticipantAction, role_permission_policy
from apps.common.responses import api_error, api_success
from apps.integration.exceptions import IntegrationError
from apps.prds.detail import PrdNotFound, PrdPermissionPresenter
from apps.prds.views import (
    _context_error,
    _request_id,
    _resolve_context,
    get_integration_repository,
)

from .models import (
    BrainstormCanvas,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
    UserCanvasViewport,
)
from .services import (
    BrainstormAccessService,
    BrainstormMutationService,
    DuplicateConnection,
    VersionConflict,
)


def _authentication_error(request):
    if request.user.is_authenticated:
        return None
    return api_error(
        code="authentication_required",
        message="로그인이 필요합니다.",
        status=401,
        request_id=_request_id(request),
    )


def _parse_json(request):
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValidationError({"body": "요청 본문이 올바른 JSON이 아닙니다."}) from exc
    if not isinstance(payload, dict):
        raise ValidationError({"body": "JSON 객체가 필요합니다."})
    return payload


def _access(request, prd_id, *, create_canvas=False):
    context = _resolve_context(request)
    service = BrainstormAccessService()
    access = service.get(prd_id=prd_id, context=context)
    if create_canvas:
        canvas, created = service.get_or_create_canvas(access=access, context=context)
        return context, access, canvas, created
    try:
        canvas = BrainstormCanvas.objects.select_related("prd").get(prd=access.prd)
    except BrainstormCanvas.DoesNotExist as exc:
        raise ValidationError({"canvas": "브레인스토밍 캔버스가 아직 없습니다."}) from exc
    canvas.validate_context(context)
    return context, access, canvas


def _error(request, exc):
    if isinstance(exc, VersionConflict):
        latest = (
            _serialize_node(exc.latest, include_deleted=True)
            if isinstance(exc.latest, BrainstormNode)
            else _serialize_connection(exc.latest)
        )
        return api_error(
            code="version_conflict",
            message="다른 사용자가 먼저 변경했습니다. 최신 내용을 확인해 주세요.",
            status=409,
            details={"latest": latest},
            request_id=_request_id(request),
        )
    if isinstance(exc, DuplicateConnection):
        return api_error(
            code="duplicate_connection",
            message="같은 두 노드 사이에 이미 연결선이 있습니다.",
            status=409,
            details={"latest": _serialize_connection(exc.connection)},
            request_id=_request_id(request),
        )
    if isinstance(exc, PrdNotFound):
        return api_error(
            code="not_found",
            message="PRD를 찾을 수 없습니다.",
            status=404,
            request_id=_request_id(request),
        )
    if isinstance(exc, ValidationError):
        details = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        return api_error(
            code="validation_error",
            message="입력값을 확인해 주세요.",
            status=400,
            details=details,
            request_id=_request_id(request),
        )
    return _context_error(request, exc)


def _serialize_node(node, *, include_deleted=False):
    data = {
        "id": str(node.pk),
        "node_type": node.node_type,
        "content": node.content,
        "color": node.color,
        "x": float(node.position_x),
        "y": float(node.position_y),
        "section_id": node.section_id,
        "author_id": node.author_id,
        "assignee_id": node.assignee_id,
        "status": node.status,
        "version": node.version,
        "updated_at": node.updated_at.isoformat(),
    }
    if include_deleted:
        data.update(
            {
                "is_deleted": node.is_deleted,
                "deleted_at": node.deleted_at.isoformat() if node.deleted_at else None,
            }
        )
    return data


def _serialize_connection(connection):
    return {
        "id": str(connection.pk),
        "node_a_id": str(connection.node_a_id),
        "node_b_id": str(connection.node_b_id),
        "version": connection.version,
        "is_deleted": connection.is_deleted,
        "updated_at": connection.updated_at.isoformat(),
    }


def _serialize_viewport(viewport):
    return {
        "viewport_x": float(viewport.viewport_x),
        "viewport_y": float(viewport.viewport_y),
        "zoom_level": float(viewport.zoom_level),
        "updated_at": viewport.updated_at.isoformat() if viewport.pk else None,
    }


def _serialize_permissions(access):
    permissions = PrdPermissionPresenter().describe(access)
    permissions["can_edit"] = bool(
        access.role
        and role_permission_policy.allows(
            access.role,
            ParticipantAction.EDIT,
            is_completed=access.prd.status == "completed",
        )
    )
    return permissions


@require_GET
def canvas(request, prd_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas_row, created = _access(request, prd_id, create_canvas=True)
        state_filter = request.GET.get("status", "all")
        if state_filter not in {"all", BrainstormNodeStatus.ACCEPTED, BrainstormNodeStatus.DEFAULT}:
            raise ValidationError({"status": "상태 필터가 올바르지 않습니다."})
        active_nodes = BrainstormNode.objects.filter(canvas=canvas_row, is_deleted=False)
        regular_notes = active_nodes.filter(node_type=BrainstormNodeType.NOTE).exclude(
            status=BrainstormNodeStatus.HELD
        )
        counts = regular_notes.aggregate(
            total=Count("id"),
            unclassified=Count("id", filter=Q(section__isnull=True)),
            accepted=Count("id", filter=Q(status=BrainstormNodeStatus.ACCEPTED)),
        )
        counts["held"] = active_nodes.filter(
            node_type=BrainstormNodeType.NOTE,
            status=BrainstormNodeStatus.HELD,
        ).count()
        visible_nodes = active_nodes.exclude(
            node_type=BrainstormNodeType.NOTE,
            status=BrainstormNodeStatus.HELD,
        )
        if state_filter != "all":
            visible_nodes = visible_nodes.filter(
                Q(node_type=BrainstormNodeType.TITLE) | Q(status=state_filter)
            )
        visible_nodes = list(visible_nodes.order_by("created_at", "id"))
        visible_ids = [node.pk for node in visible_nodes]
        connections = BrainstormConnection.objects.filter(
            canvas=canvas_row,
            is_deleted=False,
            node_a_id__in=visible_ids,
            node_b_id__in=visible_ids,
        )
        held_nodes = active_nodes.filter(
            node_type=BrainstormNodeType.NOTE,
            status=BrainstormNodeStatus.HELD,
        ).order_by("created_at", "id")
        viewport_row = UserCanvasViewport.objects.filter(
            canvas=canvas_row,
            user_id=context.user_id,
        ).first()
        if viewport_row is None:
            viewport_row = UserCanvasViewport(canvas=canvas_row, user_id=context.user_id)
        sections = access.prd.sections.filter(is_deleted=False).order_by("position", "id")
        return api_success(
            {
                "canvas": {"id": canvas_row.id, "prd_id": access.prd.id, "created": created},
                "sections": [
                    {"id": section.id, "title": section.title, "position": section.position}
                    for section in sections
                ],
                "nodes": [_serialize_node(node) for node in visible_nodes],
                "held_nodes": [_serialize_node(node) for node in held_nodes],
                "connections": [_serialize_connection(row) for row in connections],
                "counts": counts,
                "filter": state_filter,
                "viewport": _serialize_viewport(viewport_row),
                "permissions": _serialize_permissions(access),
            },
            request_id=_request_id(request),
        )
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error(request, exc)


@require_POST
def create_node(request, prd_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas_row = _access(request, prd_id)
        node = BrainstormMutationService(get_integration_repository()).create_note(
            canvas=canvas_row,
            access=access,
            context=context,
            payload=_parse_json(request),
        )
        return api_success(_serialize_node(node), status=201, request_id=_request_id(request))
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error(request, exc)


def _node_patch(request, prd_id, node_id, method_name):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas_row = _access(request, prd_id)
        node = getattr(BrainstormMutationService(get_integration_repository()), method_name)(
            canvas=canvas_row,
            access=access,
            actor_user_id=context.user_id,
            node_id=node_id,
            payload=_parse_json(request),
        )
        return api_success(_serialize_node(node), request_id=_request_id(request))
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        VersionConflict,
    ) as exc:
        return _error(request, exc)


@require_http_methods(["PATCH"])
def node_content(request, prd_id, node_id):
    return _node_patch(request, prd_id, node_id, "update_content")


@require_http_methods(["PATCH"])
def node_assignee(request, prd_id, node_id):
    return _node_patch(request, prd_id, node_id, "assign")


@require_http_methods(["PATCH"])
def node_status(request, prd_id, node_id):
    return _node_patch(request, prd_id, node_id, "change_status")


@require_http_methods(["PATCH"])
def node_position(request, prd_id, node_id):
    return _node_patch(request, prd_id, node_id, "move")


@require_http_methods(["DELETE"])
def node_delete(request, prd_id, node_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas_row = _access(request, prd_id)
        payload = _parse_json(request)
        node = BrainstormMutationService().delete_node(
            canvas=canvas_row,
            access=access,
            actor_user_id=context.user_id,
            node_id=node_id,
            version=payload.get("version"),
        )
        return api_success(
            _serialize_node(node, include_deleted=True), request_id=_request_id(request)
        )
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        VersionConflict,
    ) as exc:
        return _error(request, exc)


@require_POST
def node_restore(request, prd_id, node_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas_row = _access(request, prd_id)
        payload = _parse_json(request)
        node = BrainstormMutationService().restore_node(
            canvas=canvas_row,
            access=access,
            actor_user_id=context.user_id,
            node_id=node_id,
            version=payload.get("version"),
        )
        return api_success(
            _serialize_node(node, include_deleted=True), request_id=_request_id(request)
        )
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        VersionConflict,
    ) as exc:
        return _error(request, exc)


@require_POST
def create_connection(request, prd_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas_row = _access(request, prd_id)
        connection, created = BrainstormMutationService().create_connection(
            canvas=canvas_row,
            access=access,
            actor_user_id=context.user_id,
            payload=_parse_json(request),
            idempotency_key=request.headers.get("Idempotency-Key", ""),
        )
        return api_success(
            {"connection": _serialize_connection(connection), "created": created},
            status=201 if created else 200,
            request_id=_request_id(request),
        )
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        VersionConflict,
        DuplicateConnection,
    ) as exc:
        return _error(request, exc)


@require_http_methods(["DELETE"])
def connection_delete(request, prd_id, connection_id):
    if response := _authentication_error(request):
        return response
    try:
        context, access, canvas_row = _access(request, prd_id)
        connection = BrainstormMutationService().delete_connection(
            canvas=canvas_row,
            access=access,
            actor_user_id=context.user_id,
            connection_id=connection_id,
            version=_parse_json(request).get("version"),
        )
        return api_success(_serialize_connection(connection), request_id=_request_id(request))
    except (
        PrdNotFound,
        PermissionDenied,
        IntegrationError,
        ValidationError,
        VersionConflict,
    ) as exc:
        return _error(request, exc)


@require_http_methods(["GET", "PUT"])
def viewport(request, prd_id):
    if response := _authentication_error(request):
        return response
    try:
        context, _, canvas_row = _access(request, prd_id)
        if request.method == "PUT":
            viewport_row = BrainstormMutationService().save_viewport(
                canvas=canvas_row,
                user_id=context.user_id,
                payload=_parse_json(request),
            )
        else:
            viewport_row = UserCanvasViewport.objects.filter(
                canvas=canvas_row,
                user_id=context.user_id,
            ).first()
            if viewport_row is None:
                viewport_row = UserCanvasViewport(canvas=canvas_row, user_id=context.user_id)
        return api_success(_serialize_viewport(viewport_row), request_id=_request_id(request))
    except (PrdNotFound, PermissionDenied, IntegrationError, ValidationError) as exc:
        return _error(request, exc)
