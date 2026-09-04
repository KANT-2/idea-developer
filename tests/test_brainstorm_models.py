from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, models, transaction
from django.test import TestCase
from django.utils import timezone

from apps.brainstorm.models import (
    AuditLog,
    BrainstormCanvas,
    BrainstormChangeLog,
    BrainstormChangeTarget,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
    UserCanvasViewport,
)
from apps.integration.context import IntegrationContext
from apps.prds.models import (
    Prd,
    PrdParticipant,
    PrdParticipantRole,
    PrdSection,
    PrdType,
)


class BrainstormModelTests(TestCase):
    def setUp(self):
        self.prd = Prd.objects.create(
            title="브레인스토밍 PRD",
            prd_type=PrdType.NEW_PRODUCT,
            round_id=3,
            team_id=30,
            creator_user_id=7,
            creation_idempotency_key="brainstorm-model",
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
        self.section = PrdSection.objects.create(
            prd=self.prd,
            title="문제",
            position=1,
        )
        self.canvas = BrainstormCanvas.objects.create(prd=self.prd)
        self.context = self.make_context()

    @staticmethod
    def make_context(**overrides):
        values = {
            "user_id": 7,
            "round_id": 3,
            "participant_id": 70,
            "team_id": 30,
            "parent_role": "student",
            "is_staff": False,
            "is_superuser": False,
        }
        values.update(overrides)
        return IntegrationContext(**values)

    def make_note(self, **overrides):
        values = {
            "canvas": self.canvas,
            "node_type": BrainstormNodeType.NOTE,
            "content": "사용자 문제를 검증한다",
            "color": "yellow",
            "position_x": Decimal("100"),
            "position_y": Decimal("120"),
            "section": self.section,
            "author_id": 7,
            "assignee_id": 7,
            "status": BrainstormNodeStatus.ACCEPTED,
        }
        values.update(overrides)
        return BrainstormNode.objects.create(**values)

    def test_prd_canvas_versions_are_unique_and_context_checks_round_and_team(self):
        BrainstormCanvas.objects.create(prd=self.prd, version_number=2, source_canvas=self.canvas)
        with self.assertRaises(IntegrityError), transaction.atomic():
            BrainstormCanvas.objects.create(prd=self.prd, version_number=2)

        self.canvas.validate_context(self.context)
        for invalid_context in (
            self.make_context(round_id=4),
            self.make_context(team_id=31),
        ):
            with self.subTest(context=invalid_context), self.assertRaises(PermissionDenied):
                self.canvas.validate_context(invalid_context)

    def test_create_note_uses_authenticated_user_for_author_and_assignee(self):
        node = BrainstormNode.create_note(
            canvas=self.canvas,
            context=self.context,
            content="새 아이디어",
            color="blue",
            position_x=Decimal("10.5"),
            position_y=Decimal("20.5"),
            creation_idempotency_key="model-create-note",
        )

        self.assertIsInstance(node.pk, uuid.UUID)
        self.assertEqual(node.node_type, BrainstormNodeType.NOTE)
        self.assertEqual(node.status, BrainstormNodeStatus.DEFAULT)
        self.assertEqual((node.author_id, node.assignee_id), (7, 7))
        self.assertEqual(node.version, 1)
        self.assertIsInstance(BrainstormNode._meta.get_field("id").db_default, models.Func)

    def test_create_note_rejects_nonparticipant_and_wrong_context(self):
        with self.assertRaises(PermissionDenied):
            BrainstormNode.create_note(
                canvas=self.canvas,
                context=self.make_context(user_id=99),
                content="권한 없음",
                color="yellow",
                position_x=Decimal("0"),
                position_y=Decimal("0"),
                creation_idempotency_key="nonparticipant",
            )
        with self.assertRaises(PermissionDenied):
            BrainstormNode.create_note(
                canvas=self.canvas,
                context=self.make_context(round_id=4),
                content="다른 회차",
                color="yellow",
                position_x=Decimal("0"),
                position_y=Decimal("0"),
                creation_idempotency_key="wrong-context",
            )

    def test_title_has_no_status_author_or_assignee(self):
        title = BrainstormNode.objects.create(
            canvas=self.canvas,
            node_type=BrainstormNodeType.TITLE,
            content="문제 정의",
            color="gray",
            position_x=Decimal("0"),
            position_y=Decimal("0"),
            section=self.section,
            status=None,
            author_id=None,
            assignee_id=None,
        )
        self.assertIsNone(title.status)

        with self.assertRaises(IntegrityError), transaction.atomic():
            BrainstormNode.objects.create(
                canvas=self.canvas,
                node_type=BrainstormNodeType.TITLE,
                content="잘못된 제목",
                color="gray",
                position_x=Decimal("0"),
                position_y=Decimal("0"),
                status=BrainstormNodeStatus.ACCEPTED,
                author_id=7,
            )

    def test_section_and_assignee_must_belong_to_same_prd(self):
        other_prd = Prd.objects.create(
            title="다른 PRD",
            prd_type=PrdType.IMPROVEMENT,
            round_id=3,
            team_id=30,
            creator_user_id=9,
            creation_idempotency_key="other-brainstorm",
        )
        other_section = PrdSection.objects.create(prd=other_prd, title="다른 섹션", position=1)
        node = self.make_note(section=other_section, assignee_id=99)
        with self.assertRaises(ValidationError) as context:
            node.full_clean()
        self.assertIn("section", context.exception.message_dict)
        self.assertIn("assignee_id", context.exception.message_dict)

        node.section = self.section
        node.assignee_id = 8
        node.full_clean()

    def test_note_author_cannot_be_changed(self):
        node = self.make_note()
        node.author_id = 8
        with self.assertRaises(ValidationError):
            node.save()

    def test_connections_are_uuid_unique_undirected_and_not_self(self):
        first = self.make_note()
        second = self.make_note(content="두 번째", position_x=Decimal("200"))
        connection = BrainstormConnection.objects.create(
            canvas=self.canvas,
            node_a=first,
            node_b=second,
        )
        self.assertIsInstance(connection.pk, uuid.UUID)
        self.assertEqual(connection.version, 1)

        with self.assertRaises(IntegrityError), transaction.atomic():
            BrainstormConnection.objects.create(
                canvas=self.canvas,
                node_a=second,
                node_b=first,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            BrainstormConnection.objects.create(
                canvas=self.canvas,
                node_a=first,
                node_b=first,
            )

    def test_connection_rejects_nodes_from_another_canvas(self):
        first = self.make_note()
        other_prd = Prd.objects.create(
            title="다른 캔버스 PRD",
            prd_type=PrdType.NEW_FEATURE,
            round_id=3,
            creator_user_id=9,
            creation_idempotency_key="other-canvas",
        )
        other_canvas = BrainstormCanvas.objects.create(prd=other_prd)
        other_node = BrainstormNode.objects.create(
            canvas=other_canvas,
            node_type=BrainstormNodeType.NOTE,
            content="다른 캔버스 노드",
            color="blue",
            position_x=Decimal("0"),
            position_y=Decimal("0"),
            author_id=9,
            status=BrainstormNodeStatus.DEFAULT,
        )
        connection = BrainstormConnection(canvas=self.canvas, node_a=first, node_b=other_node)
        with self.assertRaises(ValidationError):
            connection.full_clean()

    def test_viewport_is_unique_per_user_and_zoom_is_bounded(self):
        viewport = UserCanvasViewport.objects.create(canvas=self.canvas, user_id=7)
        self.assertEqual(viewport.zoom_level, Decimal("1.00"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserCanvasViewport.objects.create(canvas=self.canvas, user_id=7)
        for invalid_zoom in (Decimal("0.29"), Decimal("2.01")):
            with (
                self.subTest(zoom=invalid_zoom),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                UserCanvasViewport.objects.create(
                    canvas=self.canvas,
                    user_id=8,
                    zoom_level=invalid_zoom,
                )

    def test_soft_delete_and_restore_follow_connected_node_state(self):
        first = self.make_note()
        second = self.make_note(content="두 번째")
        connection = BrainstormConnection.objects.create(
            canvas=self.canvas,
            node_a=first,
            node_b=second,
        )

        first.soft_delete()
        connection.refresh_from_db()
        self.assertTrue(first.is_deleted)
        self.assertTrue(connection.is_deleted)
        self.assertEqual((first.version, connection.version), (2, 2))

        second.soft_delete()
        first.restore()
        connection.refresh_from_db()
        self.assertFalse(first.is_deleted)
        self.assertTrue(connection.is_deleted)

        second.restore()
        connection.refresh_from_db()
        self.assertFalse(second.is_deleted)
        self.assertFalse(connection.is_deleted)

    def test_restore_is_rejected_after_thirty_days(self):
        node = self.make_note()
        node.soft_delete()
        BrainstormNode.objects.filter(pk=node.pk).update(
            deleted_at=timezone.now() - timedelta(days=31)
        )
        node.refresh_from_db()
        with self.assertRaises(ValidationError):
            node.restore()

    def test_hold_permanently_deletes_connections_and_audits_both_nodes(self):
        first = self.make_note()
        second = self.make_note(content="연결 메모")
        connection = BrainstormConnection.objects.create(
            canvas=self.canvas,
            node_a=first,
            node_b=second,
        )

        first.hold(actor_user_id=7)

        self.assertEqual(first.status, BrainstormNodeStatus.HELD)
        self.assertIsNone(first.section_id)
        self.assertFalse(BrainstormConnection.objects.filter(pk=connection.pk).exists())
        audit = AuditLog.objects.get(reason="node_held")
        self.assertEqual(audit.actor_user_id, 7)
        self.assertCountEqual(
            audit.details["node_ids"],
            [str(first.pk), str(second.pk)],
        )

        first.restore_from_hold(position_x=Decimal("40"), position_y=Decimal("60"))
        self.assertEqual(first.status, BrainstormNodeStatus.DEFAULT)
        self.assertIsNone(first.section_id)
        self.assertEqual((first.position_x, first.position_y), (Decimal("40"), Decimal("60")))
        self.assertFalse(BrainstormConnection.objects.exists())

    def test_change_and_audit_logs_keep_actor_target_and_payload(self):
        node = self.make_note()
        operation_id = uuid.uuid4()
        change = BrainstormChangeLog.objects.create(
            canvas=self.canvas,
            actor_user_id=7,
            operation_id=operation_id,
            action="node_moved",
            target_type=BrainstormChangeTarget.NODE,
            target_id=str(node.pk),
            before_data={"position_x": "100"},
            after_data={"position_x": "200"},
        )
        audit = AuditLog.objects.create(
            canvas=self.canvas,
            actor_user_id=7,
            action="node_created",
            target_type=BrainstormChangeTarget.NODE,
            target_id=str(node.pk),
            details={"version": 1},
        )
        self.assertEqual(change.operation_id, operation_id)
        self.assertEqual(change.after_data["position_x"], "200")
        self.assertEqual(audit.details["version"], 1)

    def test_database_rejects_unknown_state_nonpositive_version_and_bad_delete_pair(self):
        invalid_rows = (
            {"status": "pending"},
            {"version": 0},
            {"is_deleted": True, "deleted_at": None},
            {"status": BrainstormNodeStatus.HELD, "section": self.section},
            {"content": ""},
        )
        for values in invalid_rows:
            with (
                self.subTest(values=values),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                self.make_note(**values)
