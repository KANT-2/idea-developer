from datetime import date
from importlib import import_module
from unittest.mock import patch

from django.apps import apps as django_apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.brainstorm.models import (
    BrainstormCanvas,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.integration.repository import FixtureIntegrationRepository
from apps.prds.models import (
    Prd,
    PrdAnswer,
    PrdChangeHistory,
    PrdParticipant,
    PrdParticipantRole,
    PrdQuestion,
    PrdSection,
    PrdStatus,
    PrdTemplate,
    PrdTemplateQuestion,
    PrdTemplateSection,
    PrdType,
)
from apps.prds.services import CreatePrdCommand, PrdCreationService


def fixture_repository(*, active=True, approved=True, membership=True):
    users = [
        {
            "user_id": 7,
            "role": "student",
            "approval_status": "fixture-approved" if approved else "waiting",
            "is_active": active,
            "is_staff": False,
            "is_superuser": False,
            "user_email": "member@example.test",
            "primary_email": "member@example.test",
        }
    ]
    memberships = []
    if membership:
        memberships.append(
            {
                "user_id": 7,
                "round_id": 3,
                "round_title": "진행 회차",
                "round_status": "fixture-running",
                "participant_id": 10,
                "team_id": 30,
                "team_name": "현재 회차 팀",
            }
        )
    return FixtureIntegrationRepository(
        users=users,
        memberships=memberships,
        active_statuses={"fixture-running"},
    )


def make_command(**overrides):
    values = {
        "title": "새 서비스",
        "description": "한 줄 소개",
        "deadline": date(2027, 1, 31),
        "prd_type": PrdType.NEW_PRODUCT,
        "round_id": 3,
        "team_id": 30,
        "creator_user_id": 7,
        "idempotency_key": "request-001",
    }
    values.update(overrides)
    return CreatePrdCommand(**values)


class PrdModelPolicyTests(TestCase):
    def test_only_confirmed_prd_types_and_statuses_exist(self):
        self.assertEqual(set(PrdType.values), {"new_product", "new_feature", "improvement"})
        self.assertEqual(set(PrdStatus.values), {"in_progress", "completed", "held", "dropped"})

    def test_duplicate_prd_participant_is_blocked_by_database(self):
        prd = self.make_prd()
        PrdParticipant.objects.create(
            prd=prd,
            user_id=7,
            participant_id=10,
            role=PrdParticipantRole.OWNER,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrdParticipant.objects.create(
                prd=prd,
                user_id=7,
                participant_id=11,
                role=PrdParticipantRole.EDITOR,
            )

    def test_question_has_at_most_one_answer_and_history_keeps_external_actor(self):
        prd = self.make_prd()
        section = PrdSection.objects.create(prd=prd, title="문제", position=1)
        question = PrdQuestion.objects.create(
            section=section,
            prompt="누구의 문제인가요?",
            position=1,
        )
        PrdAnswer.objects.create(
            question=question,
            content="사용자의 문제입니다.",
            updated_by_user_id=7,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrdAnswer.objects.create(question=question, content="중복", updated_by_user_id=8)

        history = PrdChangeHistory.objects.create(
            prd=prd,
            actor_user_id=7,
            event_type="answer_updated",
            before_data={"content": ""},
            after_data={"content": "사용자의 문제입니다."},
        )
        self.assertEqual(history.actor_user_id, 7)

    def test_soft_delete_flag_and_timestamp_must_be_consistent(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Prd.objects.create(
                title="잘못된 삭제",
                prd_type=PrdType.IMPROVEMENT,
                round_id=3,
                creator_user_id=7,
                creation_idempotency_key="bad-delete",
                is_deleted=True,
                deleted_at=None,
            )

    def test_roundless_prd_requires_null_team_and_allows_null_external_participant(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Prd.objects.create(
                title="잘못된 개인 PRD",
                prd_type=PrdType.NEW_PRODUCT,
                round_id=None,
                team_id=30,
                creator_user_id=7,
                creation_idempotency_key="roundless-with-team",
            )

        prd = Prd.objects.create(
            title="회차 없는 개인 PRD",
            prd_type=PrdType.NEW_PRODUCT,
            round_id=None,
            team_id=None,
            creator_user_id=7,
            creation_idempotency_key="roundless-valid",
        )
        participant = PrdParticipant.objects.create(
            prd=prd,
            user_id=7,
            participant_id=None,
            role=PrdParticipantRole.OWNER,
        )
        self.assertIsNone(participant.participant_id)

    def test_roundless_prd_idempotency_is_enforced_by_database(self):
        Prd.objects.create(
            title="첫 요청",
            prd_type=PrdType.NEW_PRODUCT,
            round_id=None,
            creator_user_id=7,
            creation_idempotency_key="same-roundless-request",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Prd.objects.create(
                title="동시에 들어온 중복 요청",
                prd_type=PrdType.NEW_PRODUCT,
                round_id=None,
                creator_user_id=7,
                creation_idempotency_key="same-roundless-request",
            )

    def test_unknown_status_and_participant_role_are_blocked_by_database(self):
        prd = self.make_prd()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Prd.objects.filter(pk=prd.pk).update(status="pending")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrdParticipant.objects.create(
                prd=prd,
                user_id=7,
                participant_id=10,
                role="contributor",
            )

    def test_prd_does_not_store_derived_or_duplicate_fields(self):
        field_names = {field.name for field in Prd._meta.get_fields()}
        self.assertNotIn("days_left", field_names)
        self.assertNotIn("progress", field_names)
        self.assertNotIn("completion_score", field_names)
        self.assertNotIn("is_held", field_names)
        self.assertNotIn("is_completed", field_names)

    @staticmethod
    def make_prd():
        return Prd.objects.create(
            title="테스트 PRD",
            prd_type=PrdType.NEW_PRODUCT,
            round_id=3,
            creator_user_id=7,
            creation_idempotency_key="model-test",
        )


class PrdCompletionTests(TestCase):
    def setUp(self):
        self.prd = Prd.objects.create(
            title="완성도 PRD",
            prd_type=PrdType.IMPROVEMENT,
            round_id=3,
            creator_user_id=7,
            creation_idempotency_key="completion-test",
        )

    def test_no_questions_returns_zero(self):
        self.assertEqual(self.prd.calculate_completion_rate(), 0)
        self.assertEqual(
            Prd.objects.with_completion_rate().get(pk=self.prd.pk).completion_rate,
            0,
        )

    def test_completion_uses_only_non_deleted_questions_and_rounds_integer(self):
        section = PrdSection.objects.create(prd=self.prd, title="활성 섹션", position=1)
        PrdQuestion.objects.create(section=section, prompt="완료 1", position=1, is_completed=True)
        PrdQuestion.objects.create(section=section, prompt="완료 2", position=2, is_completed=True)
        PrdQuestion.objects.create(section=section, prompt="미완료", position=3)
        PrdQuestion.objects.create(
            section=section,
            prompt="삭제 질문",
            position=4,
            is_completed=False,
            is_deleted=True,
            deleted_at=timezone.now(),
        )
        deleted_section = PrdSection.objects.create(
            prd=self.prd,
            title="삭제 섹션",
            position=2,
            is_deleted=True,
            deleted_at=timezone.now(),
        )
        PrdQuestion.objects.create(
            section=deleted_section,
            prompt="삭제 섹션 질문",
            position=1,
            is_completed=False,
        )

        annotated = Prd.objects.with_completion_rate().get(pk=self.prd.pk)
        self.assertEqual(annotated.active_question_count, 3)
        self.assertEqual(annotated.completed_question_count, 2)
        self.assertEqual(annotated.completion_rate, 67)
        self.assertEqual(self.prd.calculate_completion_rate(), annotated.completion_rate)

    def test_completion_excludes_held_questions_from_both_counts(self):
        section = PrdSection.objects.create(prd=self.prd, title="보류 포함", position=1)
        PrdQuestion.objects.create(
            section=section,
            prompt="완료 질문",
            position=1,
            is_completed=True,
        )
        PrdQuestion.objects.create(
            section=section,
            prompt="보류된 미완료 질문",
            position=2,
            is_held=True,
        )

        annotated = Prd.objects.with_completion_rate().get(pk=self.prd.pk)
        self.assertEqual(annotated.active_question_count, 1)
        self.assertEqual(annotated.completed_question_count, 1)
        self.assertEqual(annotated.completion_rate, 100)
        self.assertEqual(self.prd.calculate_completion_rate(), 100)


class PrdCreationServiceTests(TestCase):
    def setUp(self):
        PrdTemplate.objects.all().delete()
        template = PrdTemplate.objects.create(
            prd_type=PrdType.NEW_PRODUCT,
            name="신규 프로젝트 템플릿",
        )
        problem = PrdTemplateSection.objects.create(
            template=template,
            title="문제",
            guide="사용자 문제를 설명합니다.",
            position=1,
        )
        PrdTemplateQuestion.objects.create(
            section=problem,
            prompt="어떤 문제를 해결하나요?",
            position=1,
        )
        self.service = PrdCreationService(fixture_repository())

    def test_create_validates_view_and_copies_owner_template_structure(self):
        prd, created = self.service.create(make_command())

        self.assertTrue(created)
        self.assertEqual(prd.title, "새 서비스")
        self.assertEqual(prd.description, "한 줄 소개")
        self.assertEqual(prd.deadline, date(2027, 1, 31))
        self.assertEqual(prd.status, PrdStatus.IN_PROGRESS)
        self.assertEqual((prd.round_id, prd.team_id, prd.creator_user_id), (3, 30, 7))
        owner = prd.participants.get()
        self.assertEqual(
            (owner.user_id, owner.participant_id, owner.role),
            (7, 10, PrdParticipantRole.OWNER),
        )
        section = prd.sections.get()
        self.assertEqual((section.title, section.guide), ("문제", "사용자 문제를 설명합니다."))
        self.assertEqual(section.questions.get().prompt, "어떤 문제를 해결하나요?")

    def test_same_idempotency_key_returns_first_prd(self):
        first, first_created = self.service.create(make_command())
        second, second_created = self.service.create(make_command(title="다른 제목"))
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Prd.objects.count(), 1)

    def test_roundless_creation_uses_active_parent_users_without_memberships(self):
        repository = FixtureIntegrationRepository(
            users=[
                {
                    "user_id": user_id,
                    "role": "student",
                    "approval_status": "fixture-approved",
                    "is_active": True,
                    "is_staff": False,
                    "is_superuser": False,
                    "user_email": f"user{user_id}@example.test",
                    "primary_email": f"user{user_id}@example.test",
                }
                for user_id in (7, 8)
            ],
            memberships=[],
            active_statuses={"fixture-running"},
        )

        prd, created = PrdCreationService(repository).create(
            make_command(
                round_id=None,
                team_id=None,
                participant_user_ids=(8, 8),
                idempotency_key="roundless-create",
            )
        )

        self.assertTrue(created)
        self.assertEqual((prd.round_id, prd.team_id), (None, None))
        self.assertEqual(
            list(
                prd.participants.order_by("user_id").values_list(
                    "user_id", "participant_id", "role"
                )
            ),
            [
                (7, None, PrdParticipantRole.OWNER),
                (8, None, PrdParticipantRole.EDITOR),
            ],
        )

    @patch("apps.prds.services.send_prd_participant_added")
    def test_creation_notifies_only_new_teammates_after_commit(self, send_notification):
        repository = FixtureIntegrationRepository(
            users=[
                {
                    "user_id": user_id,
                    "role": "student",
                    "approval_status": "fixture-approved",
                    "is_active": True,
                    "is_staff": False,
                    "is_superuser": False,
                    "user_email": f"user{user_id}@example.test",
                    "primary_email": f"user{user_id}@example.test",
                }
                for user_id in (7, 8, 9)
            ],
            memberships=[],
            active_statuses={"fixture-running"},
        )

        with self.captureOnCommitCallbacks(execute=True):
            prd, _ = PrdCreationService(repository).create(
                make_command(
                    round_id=None,
                    team_id=None,
                    participant_user_ids=(7, 8, 9, 8),
                    idempotency_key="notify-team",
                )
            )

        send_notification.assert_called_once_with(
            prd_id=prd.pk,
            prd_title=prd.title,
            user_ids=(8, 9),
        )
        self.assertTrue(PrdChangeHistory.objects.filter(prd=prd, event_type="prd_created").exists())

    def test_rejects_team_not_matching_current_round_membership(self):
        with self.assertRaises(PermissionDenied):
            self.service.create(make_command(team_id=999))
        self.assertFalse(Prd.objects.exists())

    def test_rejects_missing_round_membership(self):
        service = PrdCreationService(fixture_repository(membership=False))
        with self.assertRaises(PermissionDenied):
            service.create(make_command())

    def test_rejects_inactive_or_unapproved_parent_user(self):
        for repository in (
            fixture_repository(active=False),
            fixture_repository(approved=False),
        ):
            with self.subTest(repository=repository), self.assertRaises(PermissionDenied):
                PrdCreationService(repository).create(make_command())

    def test_missing_type_template_rolls_back_everything(self):
        with self.assertRaises(ValidationError):
            self.service.create(make_command(prd_type=PrdType.NEW_FEATURE))
        self.assertFalse(Prd.objects.exists())
        self.assertFalse(PrdParticipant.objects.exists())

    def test_blank_title_and_unknown_type_are_rejected(self):
        with self.assertRaises(ValidationError) as context:
            self.service.create(make_command(title="  ", prd_type="pending"))
        self.assertIn("title", context.exception.message_dict)
        self.assertIn("prd_type", context.exception.message_dict)


class ConfirmedPrdTemplateSeedTests(TestCase):
    def test_three_confirmed_templates_are_seeded_with_sections_and_questions(self):
        templates = {
            template.prd_type: template
            for template in PrdTemplate.objects.prefetch_related("sections__questions")
        }

        self.assertEqual(templates.keys(), set(PrdType.values))
        self.assertEqual(
            templates[PrdType.NEW_PRODUCT].name,
            "신규 프로젝트 PRD 템플릿",
        )
        self.assertEqual(
            templates[PrdType.NEW_FEATURE].name,
            "기존 프로젝트 신규 기능 PRD 템플릿",
        )
        self.assertEqual(
            templates[PrdType.IMPROVEMENT].name,
            "기존 기능 개선 PRD 템플릿",
        )
        self.assertTrue(all(template.sections.count() == 7 for template in templates.values()))
        self.assertTrue(
            all(
                section.questions.exists()
                for template in templates.values()
                for section in template.sections.all()
            )
        )
        self.assertEqual(
            list(templates[PrdType.NEW_PRODUCT].sections.values_list("title", flat=True)),
            [
                "프로젝트 요약",
                "서비스 목표 및 핵심 가치",
                "추진 배경 및 기회",
                "핵심 타겟 및 이용 상황",
                "문제 정의 및 솔루션 가설",
                "핵심 MVP 범위",
                "성공 지표 및 검증 계획",
            ],
        )

    def test_selected_template_is_copied_to_a_new_prd(self):
        prd, created = PrdCreationService(fixture_repository()).create(
            make_command(
                prd_type=PrdType.NEW_FEATURE,
                idempotency_key="seeded-new-feature-template",
            )
        )

        self.assertTrue(created)
        self.assertEqual(prd.sections.count(), 7)
        self.assertEqual(
            PrdQuestion.objects.filter(section__prd=prd).count(),
            46,
        )
        self.assertEqual(
            prd.sections.order_by("position").first().title,
            "기능 요약",
        )

    def test_existing_prd_answers_and_brainstorm_links_are_preserved_during_backfill(self):
        prd = Prd.objects.create(
            title="기존 PRD",
            description="기존 설명",
            prd_type=PrdType.NEW_PRODUCT,
            round_id=None,
            team_id=None,
            creator_user_id=7,
            creation_idempotency_key="legacy-prd-backfill",
        )
        legacy_sections = [
            PrdSection.objects.create(prd=prd, title=title, position=position)
            for position, title in enumerate(
                ("문제 정의", "목표와 성공 지표", "핵심 사용자 경험"),
                start=1,
            )
        ]
        legacy_question = PrdQuestion.objects.create(
            section=legacy_sections[0],
            prompt="기존 문제 질문",
            position=1,
            is_completed=True,
        )
        answer = PrdAnswer.objects.create(
            question=legacy_question,
            content="기존 답변은 유지됩니다.",
            updated_by_user_id=7,
        )
        canvas = BrainstormCanvas.objects.create(prd=prd)
        node = BrainstormNode.objects.create(
            canvas=canvas,
            node_type=BrainstormNodeType.NOTE,
            content="기존 브레인스토밍 메모",
            color="yellow",
            position_x=10,
            position_y=20,
            section=legacy_sections[0],
            author_id=7,
            assignee_id=None,
            status=BrainstormNodeStatus.ACCEPTED,
        )

        migration = import_module("apps.prds.migrations.0009_backfill_existing_prds_from_templates")
        migration.backfill_existing_prds(django_apps, None)

        prd.refresh_from_db()
        legacy_question.refresh_from_db()
        answer.refresh_from_db()
        node.refresh_from_db()
        self.assertEqual(prd.sections.filter(is_deleted=False).count(), 7)
        self.assertEqual(legacy_sections[0].pk, node.section_id)
        self.assertEqual(node.section.title, "문제 정의 및 솔루션 가설")
        self.assertEqual(node.status, BrainstormNodeStatus.ACCEPTED)
        self.assertEqual(answer.question_id, legacy_question.pk)
        self.assertEqual(answer.content, "기존 답변은 유지됩니다.")
        self.assertGreater(legacy_question.position, 6)
