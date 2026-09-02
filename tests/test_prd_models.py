from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

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


class PrdCreationServiceTests(TestCase):
    def setUp(self):
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
