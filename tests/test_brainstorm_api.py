from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import LocalUserMapping
from apps.brainstorm.models import (
    AuditLog,
    BrainstormCanvas,
    BrainstormChangeLog,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
    UserCanvasViewport,
)
from apps.brainstorm.services import BrainstormEventPublisher
from apps.integration.context import IntegrationContext
from apps.integration.repository import FixtureIntegrationRepository
from apps.prds.models import (
    Prd,
    PrdParticipant,
    PrdParticipantRole,
    PrdSection,
    PrdStatus,
    PrdType,
)


def user_row(user_id):
    return {
        "user_id": user_id,
        "user_email": f"user{user_id}@example.test",
        "primary_email": f"user{user_id}@example.test",
        "first_name": "사용자",
        "last_name": str(user_id),
        "role": "student",
        "approval_status": "fixture-approved",
        "is_active": True,
        "is_staff": False,
        "is_superuser": False,
    }


def membership_row(user_id, participant_id, *, round_id=3, team_id=30):
    return {
        "user_id": user_id,
        "round_id": round_id,
        "round_title": f"회차 {round_id}",
        "round_status": "fixture-running",
        "participant_id": participant_id,
        "team_id": team_id,
        "team_name": f"팀 {team_id}",
        "display_name_snapshot": f"사용자 {user_id}",
    }


class BrainstormApiTests(TestCase):
    def setUp(self):
        self.context = IntegrationContext(
            user_id=7,
            round_id=3,
            participant_id=70,
            team_id=30,
            parent_role="student",
            is_staff=False,
            is_superuser=False,
        )
        self.repository = FixtureIntegrationRepository(
            users=[user_row(7), user_row(8), user_row(9)],
            memberships=[
                membership_row(7, 70),
                membership_row(8, 80),
                membership_row(9, 90, team_id=31),
            ],
            active_statuses={"fixture-running"},
        )
        self.resolver = Mock()
        self.resolver.resolve.return_value = self.context
        self.resolver_patch = patch(
            "apps.prds.views.get_context_resolver",
            return_value=self.resolver,
        )
        self.repository_patch = patch(
            "apps.brainstorm.views.get_integration_repository",
            return_value=self.repository,
        )
        self.resolver_patch.start()
        self.repository_patch.start()
        self.addCleanup(self.resolver_patch.stop)
        self.addCleanup(self.repository_patch.stop)

        local_user = LocalUserMapping.objects.create_user(7, "owner@example.test")
        self.client.force_login(local_user)
        session = self.client.session
        session["selected_round_id"] = 3
        session.save()

        self.prd = Prd.objects.create(
            title="브레인스토밍 API",
            prd_type=PrdType.NEW_PRODUCT,
            round_id=3,
            team_id=30,
            creator_user_id=7,
            creation_idempotency_key="brain-api",
        )
        PrdParticipant.objects.create(
            prd=self.prd,
            user_id=7,
            participant_id=70,
            role=PrdParticipantRole.OWNER,
        )
        PrdParticipant.objects.create(
            prd=self.prd,
            user_id=8,
            participant_id=80,
            role=PrdParticipantRole.EDITOR,
        )
        self.section_a = PrdSection.objects.create(prd=self.prd, title="문제", position=1)
        self.section_b = PrdSection.objects.create(prd=self.prd, title="해결", position=2)

    def url(self, name, **kwargs):
        return reverse(f"brainstorm_api:{name}", kwargs={"prd_id": self.prd.id, **kwargs})

    def json_request(self, method, name, payload=None, *, headers=None, **kwargs):
        request_headers = dict(headers or {})
        if name == "node-create" and "HTTP_IDEMPOTENCY_KEY" not in request_headers:
            request_headers["HTTP_IDEMPOTENCY_KEY"] = f"node-{uuid.uuid4()}"
        return getattr(self.client, method)(
            self.url(name, **kwargs),
            data=json.dumps(payload or {}),
            content_type="application/json",
            **request_headers,
        )

    def initialize_canvas(self):
        response = self.client.get(
            self.url("canvas"),
            HTTP_IDEMPOTENCY_KEY="canvas-initialize",
        )
        self.assertEqual(response.status_code, 200)
        return BrainstormCanvas.objects.get(prd=self.prd)

    def create_note(self, **overrides):
        canvas = BrainstormCanvas.objects.get_or_create(prd=self.prd)[0]
        values = {
            "canvas": canvas,
            "node_type": BrainstormNodeType.NOTE,
            "content": "기본 메모",
            "color": "yellow",
            "position_x": Decimal("10"),
            "position_y": Decimal("20"),
            "author_id": 7,
            "assignee_id": 7,
            "status": BrainstormNodeStatus.DEFAULT,
        }
        values.update(overrides)
        if "status" not in overrides and values.get("section") is not None:
            values["status"] = BrainstormNodeStatus.ACCEPTED
        return BrainstormNode.objects.create(**values)

    def test_canvas_is_created_once_and_returns_counts_filter_and_viewport(self):
        canvas = self.initialize_canvas()
        self.create_note(canvas=canvas)
        self.create_note(
            canvas=canvas,
            content="채택",
            status=BrainstormNodeStatus.ACCEPTED,
            section=self.section_a,
        )
        self.create_note(canvas=canvas, content="보류", status=BrainstormNodeStatus.HELD)

        response = self.client.get(self.url("canvas"), {"status": "accepted"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertFalse(data["canvas"]["created"])
        self.assertEqual(data["current_user_id"], 7)
        self.assertEqual(BrainstormCanvas.objects.filter(prd=self.prd).count(), 1)
        self.assertEqual(
            data["counts"],
            {"total": 2, "unclassified": 1, "accepted": 1, "held": 1},
        )
        self.assertEqual([row["status"] for row in data["nodes"]], ["accepted"])
        self.assertEqual(len(data["held_nodes"]), 1)
        self.assertEqual(data["viewport"]["zoom_level"], 1.0)
        self.assertEqual(
            data["participants"],
            [
                {"user_id": 7, "role": "owner", "display_name": "사용자 7"},
                {"user_id": 8, "role": "editor", "display_name": "사용자 8"},
            ],
        )

    def test_context_round_team_and_prd_role_are_checked_on_every_request(self):
        self.initialize_canvas()
        for bad_context in (
            IntegrationContext(7, 4, 70, 30, "student", False, False),
            IntegrationContext(7, 3, 70, 31, "student", False, False),
        ):
            with self.subTest(context=bad_context):
                self.resolver.resolve.return_value = bad_context
                response = self.client.get(self.url("canvas"))
                self.assertEqual(response.status_code, 403)

        self.resolver.resolve.return_value = self.context
        self.prd.participants.filter(user_id=7).update(role=PrdParticipantRole.VIEWER)
        response = self.json_request(
            "post",
            "node-create",
            {"content": "금지", "color": "yellow", "x": 0, "y": 0},
        )
        self.assertEqual(response.status_code, 403)

    def test_note_creation_uses_context_identity_and_validates_section(self):
        self.initialize_canvas()
        response = self.json_request(
            "post",
            "node-create",
            {
                "content": "새로운 아이디어",
                "color": "blue",
                "x": 30.5,
                "y": 40.5,
                "section_id": self.section_a.id,
                "author_id": 999,
                "assignee_id": 999,
            },
        )

        self.assertEqual(response.status_code, 201)
        node = BrainstormNode.objects.get()
        self.assertEqual((node.author_id, node.assignee_id), (7, 7))
        self.assertEqual(node.section_id, self.section_a.id)
        self.assertEqual(node.status, BrainstormNodeStatus.ACCEPTED)
        self.assertEqual(node.version, 1)

    def test_canvas_and_note_creation_require_and_reuse_idempotency_keys(self):
        missing_canvas_key = self.client.get(self.url("canvas"))
        self.assertEqual(missing_canvas_key.status_code, 400)
        self.initialize_canvas()

        payload = {"content": "중복 방지", "color": "yellow", "x": 1, "y": 2}
        missing_note_key = self.client.post(
            self.url("node-create"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        first = self.json_request(
            "post",
            "node-create",
            payload,
            headers={"HTTP_IDEMPOTENCY_KEY": "same-node-key"},
        )
        retry = self.json_request(
            "post",
            "node-create",
            payload,
            headers={"HTTP_IDEMPOTENCY_KEY": "same-node-key"},
        )
        changed = self.json_request(
            "post",
            "node-create",
            {**payload, "content": "다른 내용"},
            headers={"HTTP_IDEMPOTENCY_KEY": "same-node-key"},
        )

        self.assertEqual(missing_note_key.status_code, 400)
        self.assertEqual(
            (first.status_code, retry.status_code, changed.status_code),
            (201, 200, 400),
        )
        self.assertTrue(first.json()["data"]["created"])
        self.assertFalse(retry.json()["data"]["created"])
        self.assertEqual(BrainstormNode.objects.count(), 1)

    def test_note_content_length_and_color_are_validated(self):
        self.initialize_canvas()
        too_long = self.json_request(
            "post",
            "node-create",
            {"content": "x" * 4001, "color": "yellow", "x": 0, "y": 0},
        )
        invalid_color = self.json_request(
            "post",
            "node-create",
            {"content": "메모", "color": "javascript:red", "x": 0, "y": 0},
        )

        self.assertEqual(too_long.status_code, 400)
        self.assertIn("4000", str(too_long.json()["error"]["details"]))
        self.assertEqual(invalid_color.status_code, 400)
        self.assertFalse(BrainstormNode.objects.exists())

    def test_content_update_requires_version_and_returns_latest_on_conflict(self):
        node = self.create_note()
        success = self.json_request(
            "patch",
            "node-content",
            {"content": "수정됨", "version": 1},
            node_id=node.pk,
        )
        conflict = self.json_request(
            "patch",
            "node-content",
            {"content": "오래된 수정", "version": 1},
            node_id=node.pk,
        )

        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.json()["data"]["version"], 2)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "version_conflict")
        self.assertEqual(conflict.json()["error"]["details"]["latest"]["content"], "수정됨")

    def test_assignee_must_be_active_current_round_prd_participant(self):
        node = self.create_note()
        success = self.json_request(
            "patch",
            "node-assignee",
            {"assignee_id": 8, "version": 1},
            node_id=node.pk,
        )
        invalid = self.json_request(
            "patch",
            "node-assignee",
            {"assignee_id": 9, "version": 2},
            node_id=node.pk,
        )
        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.json()["data"]["assignee_id"], 8)
        self.assertEqual(invalid.status_code, 400)

    def test_position_supports_all_section_movement_directions(self):
        node = self.create_note(section=None)
        moves = (
            (self.section_a.id, 1, 2),
            (self.section_b.id, 3, 4),
            (None, 5, 6),
            (None, 7, 8),
        )
        for version, (section_id, x, y) in enumerate(moves, start=1):
            response = self.json_request(
                "patch",
                "node-position",
                {"section_id": section_id, "x": x, "y": y, "version": version},
                node_id=node.pk,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["data"]["status"],
                "accepted" if section_id is not None else "default",
            )
        node.refresh_from_db()
        self.assertIsNone(node.section_id)
        self.assertEqual((node.position_x, node.position_y), (Decimal("7"), Decimal("8")))

    def test_connection_creation_is_idempotent_and_rejects_invalid_connections(self):
        first = self.create_note()
        second = self.create_note(content="두 번째")
        payload = {
            "node_a_id": str(first.pk),
            "node_b_id": str(second.pk),
            "node_a_version": 1,
            "node_b_version": 1,
        }
        first_response = self.json_request(
            "post",
            "connection-create",
            payload,
            headers={"HTTP_IDEMPOTENCY_KEY": "connection-1"},
        )
        retry = self.json_request(
            "post",
            "connection-create",
            payload,
            headers={"HTTP_IDEMPOTENCY_KEY": "connection-1"},
        )
        duplicate = self.json_request(
            "post",
            "connection-create",
            payload,
            headers={"HTTP_IDEMPOTENCY_KEY": "connection-2"},
        )
        self_link = self.json_request(
            "post",
            "connection-create",
            {**payload, "node_b_id": str(first.pk)},
            headers={"HTTP_IDEMPOTENCY_KEY": "connection-3"},
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertFalse(retry.json()["data"]["created"])
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self_link.status_code, 400)
        self.assertEqual(BrainstormConnection.objects.count(), 1)

    def test_connection_rejects_other_canvas_and_deleted_nodes(self):
        first = self.create_note()
        second = self.create_note(content="삭제 노드")
        second.soft_delete()
        deleted_response = self.json_request(
            "post",
            "connection-create",
            {
                "node_a_id": str(first.pk),
                "node_b_id": str(second.pk),
                "node_a_version": first.version,
                "node_b_version": second.version,
            },
            headers={"HTTP_IDEMPOTENCY_KEY": "deleted-node"},
        )

        other_prd = Prd.objects.create(
            title="다른 캔버스",
            prd_type=PrdType.IMPROVEMENT,
            round_id=3,
            team_id=30,
            creator_user_id=7,
            creation_idempotency_key="other-canvas-api",
        )
        other_canvas = BrainstormCanvas.objects.create(prd=other_prd)
        other_node = BrainstormNode.objects.create(
            canvas=other_canvas,
            node_type=BrainstormNodeType.NOTE,
            content="다른 노드",
            color="blue",
            position_x=0,
            position_y=0,
            author_id=7,
            assignee_id=7,
            status=BrainstormNodeStatus.DEFAULT,
        )
        other_response = self.json_request(
            "post",
            "connection-create",
            {
                "node_a_id": str(first.pk),
                "node_b_id": str(other_node.pk),
                "node_a_version": first.version,
                "node_b_version": other_node.version,
            },
            headers={"HTTP_IDEMPOTENCY_KEY": "other-canvas"},
        )
        self.assertEqual(deleted_response.status_code, 400)
        self.assertEqual(other_response.status_code, 400)

    def test_connection_delete_requires_version(self):
        first = self.create_note()
        second = self.create_note(content="두 번째")
        connection = BrainstormConnection.objects.create(
            canvas=first.canvas,
            node_a=first,
            node_b=second,
            creation_idempotency_key="delete-test",
        )
        conflict = self.json_request(
            "delete",
            "connection-delete",
            {"version": 2},
            connection_id=connection.pk,
        )
        success = self.json_request(
            "delete",
            "connection-delete",
            {"version": 1},
            connection_id=connection.pk,
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(success.status_code, 200)
        connection.refresh_from_db()
        self.assertTrue(connection.is_deleted)
        self.assertEqual(connection.version, 2)

    def test_hold_is_atomic_audited_and_restores_without_connections(self):
        first = self.create_note(section=self.section_a)
        second = self.create_note(content="연결")
        connection = BrainstormConnection.objects.create(
            canvas=first.canvas,
            node_a=first,
            node_b=second,
            creation_idempotency_key="held-connection",
        )
        held = self.json_request(
            "patch",
            "node-status",
            {
                "status": "held",
                "version": 1,
                "connection_versions": [{"id": str(connection.pk), "version": 1}],
            },
            node_id=first.pk,
        )
        restored = self.json_request(
            "patch",
            "node-status",
            {"status": "default", "version": 2},
            node_id=first.pk,
        )

        self.assertEqual(held.status_code, 200)
        self.assertIsNone(held.json()["data"]["section_id"])
        self.assertFalse(BrainstormConnection.objects.exists())
        self.assertEqual(AuditLog.objects.get().reason, "node_held")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()["data"]["status"], "default")
        self.assertFalse(BrainstormConnection.objects.exists())

    def test_hold_rejects_stale_connection_versions_without_partial_changes(self):
        first = self.create_note(section=self.section_a)
        second = self.create_note(content="연결")
        connection = BrainstormConnection.objects.create(
            canvas=first.canvas,
            node_a=first,
            node_b=second,
            creation_idempotency_key="hold-conflict",
        )

        response = self.json_request(
            "patch",
            "node-status",
            {
                "status": "held",
                "version": 1,
                "connection_versions": [{"id": str(connection.pk), "version": 2}],
            },
            node_id=first.pk,
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "connection_version_conflict")
        first.refresh_from_db()
        self.assertEqual(first.status, BrainstormNodeStatus.ACCEPTED)
        self.assertEqual(first.section_id, self.section_a.id)
        self.assertTrue(BrainstormConnection.objects.filter(pk=connection.pk).exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_multiple_hold_restores_receive_non_overlapping_default_positions(self):
        first = self.create_note(status=BrainstormNodeStatus.HELD, section=None)
        second = self.create_note(
            content="두 번째 보류",
            status=BrainstormNodeStatus.HELD,
            section=None,
        )
        first_response = self.json_request(
            "patch",
            "node-status",
            {"status": "default", "version": 1},
            node_id=first.pk,
        )
        second_response = self.json_request(
            "patch",
            "node-status",
            {"status": "default", "version": 1},
            node_id=second.pk,
        )
        first_position = (first_response.json()["data"]["x"], first_response.json()["data"]["y"])
        second_position = (
            second_response.json()["data"]["x"],
            second_response.json()["data"]["y"],
        )
        self.assertNotEqual(first_position, second_position)

    def test_soft_delete_and_restore_restore_only_live_endpoint_connections(self):
        first = self.create_note()
        second = self.create_note(content="상대 노드")
        connection = BrainstormConnection.objects.create(
            canvas=first.canvas,
            node_a=first,
            node_b=second,
            creation_idempotency_key="soft-delete",
        )
        deleted = self.json_request(
            "delete",
            "node-delete",
            {"version": 1},
            node_id=first.pk,
        )
        second.soft_delete()
        restored = self.json_request(
            "post",
            "node-restore",
            {"version": deleted.json()["data"]["version"]},
            node_id=first.pk,
        )
        connection.refresh_from_db()
        self.assertEqual(restored.status_code, 200)
        self.assertTrue(connection.is_deleted)

    def test_viewport_is_saved_and_read_per_user(self):
        self.initialize_canvas()
        saved = self.json_request(
            "put",
            "viewport",
            {"viewport_x": 120, "viewport_y": -40, "zoom_level": 1.5},
        )
        read = self.client.get(self.url("viewport"))
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(read.json()["data"]["viewport_x"], 120.0)
        self.assertEqual(read.json()["data"]["zoom_level"], 1.5)
        self.assertEqual(UserCanvasViewport.objects.count(), 1)

    def test_completed_prd_blocks_mutation_and_anonymous_is_rejected(self):
        self.initialize_canvas()
        first = self.create_note()
        second = self.create_note(content="두 번째")
        connection = BrainstormConnection.objects.create(
            canvas=first.canvas,
            node_a=first,
            node_b=second,
            creation_idempotency_key="completed-lock",
        )
        self.prd.status = PrdStatus.COMPLETED
        self.prd.save(update_fields=["status", "updated_at"])
        detail = self.client.get(self.url("canvas"))
        blocked_requests = (
            self.json_request(
                "post",
                "node-create",
                {"content": "완료 후", "color": "yellow", "x": 0, "y": 0},
            ),
            self.json_request(
                "patch",
                "node-content",
                {"content": "수정", "version": 1},
                node_id=first.pk,
            ),
            self.json_request(
                "patch",
                "node-assignee",
                {"assignee_id": 8, "version": 1},
                node_id=first.pk,
            ),
            self.json_request(
                "patch",
                "node-status",
                {"status": "accepted", "version": 1},
                node_id=first.pk,
            ),
            self.json_request(
                "patch",
                "node-position",
                {"section_id": self.section_a.id, "x": 1, "y": 2, "version": 1},
                node_id=first.pk,
            ),
            self.json_request("delete", "node-delete", {"version": 1}, node_id=first.pk),
            self.json_request(
                "post",
                "connection-create",
                {
                    "node_a_id": str(first.pk),
                    "node_b_id": str(second.pk),
                    "node_a_version": 1,
                    "node_b_version": 1,
                },
                headers={"HTTP_IDEMPOTENCY_KEY": "completed-new-connection"},
            ),
            self.json_request(
                "delete",
                "connection-delete",
                {"version": 1},
                connection_id=connection.pk,
            ),
        )
        self.client.logout()
        anonymous = self.client.get(self.url("canvas"))
        self.assertFalse(detail.json()["data"]["permissions"]["can_edit"])
        self.assertTrue(all(response.status_code == 403 for response in blocked_requests))
        self.assertEqual(anonymous.status_code, 401)

    def test_auto_layout_updates_all_eligible_notes_as_one_operation(self):
        first = self.create_note(section=self.section_a)
        second = self.create_note(content="미분류", section=None)
        held = self.create_note(content="보류", status=BrainstormNodeStatus.HELD)
        title = BrainstormNode.objects.create(
            canvas=first.canvas,
            node_type=BrainstormNodeType.TITLE,
            content="제목",
            color="gray",
            position_x=900,
            position_y=900,
            status=None,
            author_id=None,
            assignee_id=None,
        )
        response = self.json_request(
            "post",
            "auto-layout",
            {
                "nodes": [
                    {
                        "id": str(first.pk),
                        "version": 1,
                        "x": 100,
                        "y": 120,
                        "section_id": self.section_a.id,
                    },
                    {
                        "id": str(second.pk),
                        "version": 1,
                        "x": 40,
                        "y": 50,
                        "section_id": None,
                    },
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        held.refresh_from_db()
        title.refresh_from_db()
        self.assertEqual((first.position_x, first.position_y, first.version), (100, 120, 2))
        self.assertEqual((second.position_x, second.position_y, second.version), (40, 50, 2))
        self.assertEqual(held.version, 1)
        self.assertEqual(title.version, 1)
        log = BrainstormChangeLog.objects.get(action="auto_layout_applied")
        self.assertEqual(str(log.operation_id), response.json()["data"]["operation_id"])
        self.assertEqual(len(log.before_data["nodes"]), 2)
        self.assertEqual(len(log.after_data["nodes"]), 2)

    def test_auto_layout_conflict_rolls_back_every_node(self):
        first = self.create_note()
        second = self.create_note(content="두 번째")
        second.version = 2
        second.save(update_fields=["version", "updated_at"])
        response = self.json_request(
            "post",
            "auto-layout",
            {
                "nodes": [
                    {
                        "id": str(first.pk),
                        "version": 1,
                        "x": 500,
                        "y": 500,
                        "section_id": None,
                    },
                    {
                        "id": str(second.pk),
                        "version": 1,
                        "x": 600,
                        "y": 600,
                        "section_id": None,
                    },
                ]
            },
        )

        self.assertEqual(response.status_code, 409)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.position_x, first.position_y, first.version), (10, 20, 1))
        self.assertEqual((second.position_x, second.position_y, second.version), (10, 20, 2))
        self.assertFalse(BrainstormChangeLog.objects.exists())

    def test_auto_layout_requires_exact_eligible_set_and_preserves_sections(self):
        first = self.create_note(section=self.section_a)
        second = self.create_note(content="두 번째")
        missing = self.json_request(
            "post",
            "auto-layout",
            {
                "nodes": [
                    {
                        "id": str(first.pk),
                        "version": 1,
                        "x": 1,
                        "y": 1,
                        "section_id": self.section_a.id,
                    }
                ]
            },
        )
        changed_section = self.json_request(
            "post",
            "auto-layout",
            {
                "nodes": [
                    {
                        "id": str(first.pk),
                        "version": 1,
                        "x": 1,
                        "y": 1,
                        "section_id": self.section_b.id,
                    },
                    {
                        "id": str(second.pk),
                        "version": 1,
                        "x": 2,
                        "y": 2,
                        "section_id": None,
                    },
                ]
            },
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(changed_section.status_code, 400)

    def test_polling_returns_incremental_events_snapshots_and_counts(self):
        self.initialize_canvas()
        initial = self.client.get(self.url("canvas")).json()["data"]
        created = self.json_request(
            "post",
            "node-create",
            {"content": "polling 메모", "color": "blue", "x": 1, "y": 2},
        )
        response = self.client.get(self.url("events"), {"cursor": initial["cursor"]})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertFalse(data["reset_required"])
        self.assertEqual(len(data["events"]), 1)
        event = data["events"][0]
        self.assertEqual(event["action"], "node_created")
        self.assertEqual(event["snapshot"]["id"], created.json()["data"]["id"])
        self.assertEqual(data["counts"]["total"], 1)
        self.assertGreater(data["cursor"], initial["cursor"])

    def test_invalid_or_missing_cursor_requires_full_state_reload(self):
        self.initialize_canvas()
        for query in ({}, {"cursor": "not-a-number"}, {"cursor": 999999}):
            with self.subTest(query=query):
                response = self.client.get(self.url("events"), query)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["data"]["reset_required"])

    def test_change_history_uses_operation_units_and_excludes_audit_log(self):
        canvas = self.initialize_canvas()
        BrainstormEventPublisher.prd_apply_completed(
            canvas=canvas,
            actor_user_id=7,
            application_id="apply-1",
        )
        AuditLog.objects.create(
            canvas=canvas,
            actor_user_id=7,
            action="security_check",
            target_type="canvas",
            target_id=str(canvas.pk),
            reason="audit_only",
        )
        response = self.client.get(self.url("change-history"))
        items = response.json()["data"]["items"]
        polling = self.client.get(self.url("events"), {"cursor": 0}).json()["data"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["action"], "prd_apply_completed")
        self.assertTrue(items[0]["operation_id"])
        self.assertEqual(polling["events"][0]["action"], "prd_apply_completed")

    def test_brainstorm_page_provides_api_base_for_react_polling(self):
        response = self.client.get(reverse("brainstorm-page", kwargs={"prd_id": self.prd.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-prd-id="{self.prd.id}"')
        self.assertContains(
            response,
            f'data-api-base="/api/v1/prds/{self.prd.id}/brainstorm/"',
        )
        self.assertContains(response, 'data-polling-interval-ms="3000"')
