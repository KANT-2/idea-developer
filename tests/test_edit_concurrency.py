from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from django.db import close_old_connections
from django.test import Client, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import LocalUserMapping
from apps.brainstorm.models import BrainstormCanvas, BrainstormNode
from apps.brainstorm.services import BrainstormAccessService
from apps.integration.context import IntegrationContext
from apps.integration.repository import FixtureIntegrationRepository
from apps.prds.detail import PrdPermissionPresenter
from apps.prds.models import (
    Prd,
    PrdAnswer,
    PrdComment,
    PrdCommentType,
    PrdParticipant,
    PrdParticipantRole,
    PrdQuestion,
    PrdSection,
    PrdStatus,
    PrdType,
)


class _SessionResolver:
    def resolve(self, request, *, round_id=None):
        user_id = request.user.external_user_id
        return IntegrationContext(
            user_id=user_id,
            round_id=3,
            participant_id=user_id * 10,
            team_id=30,
            parent_role="student",
            is_staff=False,
            is_superuser=False,
        )


@skipUnlessDBFeature("has_select_for_update")
class PostgreSqlEditConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.resolver_patch = patch(
            "apps.prds.views.get_context_resolver",
            return_value=_SessionResolver(),
        )
        self.resolver_patch.start()
        self.addCleanup(self.resolver_patch.stop)
        self.repository_patch = patch(
            "apps.prds.detail_views.get_integration_repository",
            return_value=FixtureIntegrationRepository(
                users=[
                    {
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
                    for user_id in (7, 8)
                ],
                memberships=[
                    {
                        "user_id": user_id,
                        "round_id": 3,
                        "round_title": "회차 3",
                        "round_status": "fixture-running",
                        "participant_id": user_id * 10,
                        "team_id": 30,
                        "team_name": "팀 30",
                        "display_name_snapshot": f"사용자 {user_id}",
                    }
                    for user_id in (7, 8)
                ],
            ),
        )
        self.repository_patch.start()
        self.addCleanup(self.repository_patch.stop)

        self.owner = LocalUserMapping.objects.create_user(7, "owner@example.test")
        self.editor = LocalUserMapping.objects.create_user(8, "editor@example.test")
        self.owner_client = Client()
        self.editor_client = Client()
        self.owner_client.force_login(self.owner)
        self.editor_client.force_login(self.editor)

        self.prd = Prd.objects.create(
            title="동시 편집 테스트",
            description="PostgreSQL 행 잠금 검증",
            deadline=timezone.localdate() + timedelta(days=30),
            prd_type=PrdType.NEW_PRODUCT,
            status=PrdStatus.IN_PROGRESS,
            round_id=3,
            team_id=30,
            creator_user_id=7,
            creation_idempotency_key="postgres-concurrency-prd",
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
        self.section = PrdSection.objects.create(prd=self.prd, title="문제", position=1)
        self.question = PrdQuestion.objects.create(
            section=self.section,
            prompt="어떤 문제인가요?",
            position=1,
            is_completed=True,
        )
        PrdAnswer.objects.create(
            question=self.question,
            content="기존 답변",
            updated_by_user_id=7,
        )
        self.comment = PrdComment.objects.create(
            prd=self.prd,
            author_user_id=7,
            author_role_at_created=PrdParticipantRole.OWNER,
            comment_type=PrdCommentType.GENERAL,
            content="기존 코멘트",
            is_contribution_eligible=True,
        )
        self.canvas = BrainstormCanvas.objects.create(
            prd=self.prd,
            created_by_user_id=7,
            creation_idempotency_key="postgres-concurrency-canvas",
        )
        self.node = BrainstormNode.create_note(
            canvas=self.canvas,
            context=_SessionResolver().resolve(type("Request", (), {"user": self.owner})()),
            content="동시 편집 메모",
            color="yellow",
            position_x=10,
            position_y=20,
            section=None,
            creation_idempotency_key="postgres-concurrency-node",
        )

    @staticmethod
    def _thread_request(callback):
        close_old_connections()
        try:
            return callback()
        finally:
            close_old_connections()

    def test_same_question_concurrent_updates_allow_only_one_writer(self):
        url = reverse(
            "prd_api:question-answer",
            kwargs={"prd_id": self.prd.pk, "question_id": self.question.pk},
        )
        barrier = threading.Barrier(2)

        def update(client, content):
            barrier.wait(timeout=5)
            return client.patch(
                url,
                data=json.dumps({"content": content, "version": 1}),
                content_type="application/json",
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._thread_request, lambda: update(self.owner_client, "답변 A")),
                executor.submit(self._thread_request, lambda: update(self.editor_client, "답변 B")),
            ]
            statuses = sorted(future.result(timeout=10) for future in futures)

        self.assertEqual(statuses, [200, 409])
        self.question.refresh_from_db()
        self.assertEqual(self.question.version, 2)
        self.assertIn(self.question.answer.content, {"답변 A", "답변 B"})

    def test_same_question_concurrent_answer_update_and_hold_allow_only_one_writer(self):
        answer_url = reverse(
            "prd_api:question-answer",
            kwargs={"prd_id": self.prd.pk, "question_id": self.question.pk},
        )
        hold_url = reverse(
            "prd_api:question-hold",
            kwargs={"prd_id": self.prd.pk, "question_id": self.question.pk},
        )
        barrier = threading.Barrier(2)

        def update():
            barrier.wait(timeout=5)
            return self.owner_client.patch(
                answer_url,
                data=json.dumps({"content": "보류와 동시에 작성한 답변", "version": 1}),
                content_type="application/json",
            ).status_code

        def hold():
            barrier.wait(timeout=5)
            return self.editor_client.patch(
                hold_url,
                data=json.dumps({"is_held": True, "version": 1}),
                content_type="application/json",
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._thread_request, update),
                executor.submit(self._thread_request, hold),
            ]
            statuses = sorted(future.result(timeout=10) for future in futures)

        self.assertEqual(statuses, [200, 409])
        self.question.refresh_from_db()
        self.assertEqual(self.question.version, 2)
        if self.question.is_held:
            self.assertEqual(self.question.answer.content, "기존 답변")
        else:
            self.assertEqual(self.question.answer.content, "보류와 동시에 작성한 답변")

    def test_same_note_concurrent_moves_allow_only_one_writer(self):
        url = reverse(
            "brainstorm_api:node-position",
            kwargs={"prd_id": self.prd.pk, "node_id": self.node.pk},
        )
        barrier = threading.Barrier(2)

        def move(client, x, y):
            barrier.wait(timeout=5)
            return client.patch(
                url,
                data=json.dumps({"x": x, "y": y, "section_id": None, "version": 1}),
                content_type="application/json",
                HTTP_X_BRAINSTORM_CANVAS_ID=str(self.canvas.pk),
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._thread_request, lambda: move(self.owner_client, 100, 120)),
                executor.submit(self._thread_request, lambda: move(self.editor_client, 200, 220)),
            ]
            statuses = sorted(future.result(timeout=10) for future in futures)

        self.assertEqual(statuses, [200, 409])
        self.node.refresh_from_db()
        self.assertEqual(self.node.version, 2)
        self.assertIn(
            (self.node.position_x, self.node.position_y),
            {(100, 120), (200, 220)},
        )

    def test_twenty_participants_can_create_notes_at_once_without_loss(self):
        """A presentation-sized burst must create every independently keyed note."""
        participant_count = 20
        barrier = threading.Barrier(participant_count)
        clients = []
        for offset in range(participant_count):
            user_id = 100 + offset
            user = LocalUserMapping.objects.create_user(
                user_id,
                f"load-user-{user_id}@example.test",
            )
            PrdParticipant.objects.create(
                prd=self.prd,
                user_id=user_id,
                participant_id=1000 + user_id,
                role=PrdParticipantRole.EDITOR,
            )
            client = Client()
            client.force_login(user)
            clients.append((client, user_id))

        url = reverse("brainstorm_api:node-create", kwargs={"prd_id": self.prd.pk})

        def create(client, user_id):
            barrier.wait(timeout=10)
            response = client.post(
                url,
                data=json.dumps(
                    {
                        "content": f"사용자 {user_id}의 동시 생성 메모",
                        "color": "yellow",
                        "x": 100 + user_id,
                        "y": 200 + user_id,
                        "section_id": None,
                    }
                ),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=f"twenty-user-create-{user_id}",
                HTTP_X_BRAINSTORM_CANVAS_ID=str(self.canvas.pk),
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=participant_count) as executor:
            futures = [
                executor.submit(self._thread_request, lambda c=client, u=user_id: create(c, u))
                for client, user_id in clients
            ]
            statuses = [future.result(timeout=30) for future in futures]

        self.assertEqual(statuses.count(201), participant_count)
        self.assertEqual(
            BrainstormNode.objects.filter(
                canvas=self.canvas,
                content__startswith="사용자 ",
            ).count(),
            participant_count,
        )

    def test_same_note_concurrent_content_update_and_delete_returns_conflict(self):
        content_url = reverse(
            "brainstorm_api:node-content",
            kwargs={"prd_id": self.prd.pk, "node_id": self.node.pk},
        )
        delete_url = reverse(
            "brainstorm_api:node-delete",
            kwargs={"prd_id": self.prd.pk, "node_id": self.node.pk},
        )
        barrier = threading.Barrier(2)

        def update():
            barrier.wait(timeout=5)
            response = self.owner_client.patch(
                content_url,
                data=json.dumps({"content": "수정된 내용", "version": 1}),
                content_type="application/json",
                HTTP_X_BRAINSTORM_CANVAS_ID=str(self.canvas.pk),
            )
            return response.status_code

        def delete():
            barrier.wait(timeout=5)
            response = self.editor_client.delete(
                delete_url,
                data=json.dumps({"version": 1}),
                content_type="application/json",
                HTTP_X_BRAINSTORM_CANVAS_ID=str(self.canvas.pk),
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._thread_request, update),
                executor.submit(self._thread_request, delete),
            ]
            statuses = sorted(future.result(timeout=10) for future in futures)

        self.assertEqual(statuses, [200, 409])
        self.node.refresh_from_db()
        self.assertEqual(self.node.version, 2)
        if self.node.is_deleted:
            self.assertEqual(self.node.content, "동시 편집 메모")
        else:
            self.assertEqual(self.node.content, "수정된 내용")

    def test_create_update_and_delete_different_notes_can_finish_together(self):
        deletable = BrainstormNode.create_note(
            canvas=self.canvas,
            context=_SessionResolver().resolve(type("Request", (), {"user": self.owner})()),
            content="동시 삭제 대상",
            color="yellow",
            position_x=300,
            position_y=320,
            section=None,
            creation_idempotency_key="mixed-delete-target",
        )
        create_url = reverse("brainstorm_api:node-create", kwargs={"prd_id": self.prd.pk})
        update_url = reverse(
            "brainstorm_api:node-content",
            kwargs={"prd_id": self.prd.pk, "node_id": self.node.pk},
        )
        delete_url = reverse(
            "brainstorm_api:node-delete",
            kwargs={"prd_id": self.prd.pk, "node_id": deletable.pk},
        )
        barrier = threading.Barrier(3)

        def create():
            barrier.wait(timeout=5)
            return self.owner_client.post(
                create_url,
                data=json.dumps(
                    {
                        "content": "혼합 작업 중 생성",
                        "color": "blue",
                        "x": 500,
                        "y": 520,
                        "section_id": None,
                    }
                ),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="mixed-operation-create",
                HTTP_X_BRAINSTORM_CANVAS_ID=str(self.canvas.pk),
            ).status_code

        def update():
            barrier.wait(timeout=5)
            return self.editor_client.patch(
                update_url,
                data=json.dumps({"content": "혼합 작업 중 수정", "version": 1}),
                content_type="application/json",
                HTTP_X_BRAINSTORM_CANVAS_ID=str(self.canvas.pk),
            ).status_code

        def delete():
            client = Client()
            client.force_login(LocalUserMapping.objects.get(pk=self.owner.pk))
            barrier.wait(timeout=5)
            return client.delete(
                delete_url,
                data=json.dumps({"version": 1}),
                content_type="application/json",
                HTTP_X_BRAINSTORM_CANVAS_ID=str(self.canvas.pk),
            ).status_code

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(self._thread_request, create),
                executor.submit(self._thread_request, update),
                executor.submit(self._thread_request, delete),
            ]
            statuses = sorted(future.result(timeout=15) for future in futures)

        self.assertEqual(statuses, [200, 200, 201])
        self.node.refresh_from_db()
        deletable.refresh_from_db()
        self.assertEqual(self.node.content, "혼합 작업 중 수정")
        self.assertTrue(deletable.is_deleted)
        self.assertTrue(
            BrainstormNode.objects.filter(
                canvas=self.canvas,
                content="혼합 작업 중 생성",
                is_deleted=False,
            ).exists()
        )

    def test_concurrent_retries_with_same_idempotency_key_create_only_one_note(self):
        url = reverse("brainstorm_api:node-create", kwargs={"prd_id": self.prd.pk})
        barrier = threading.Barrier(2)
        payload = {
            "content": "동일 생성 요청",
            "color": "green",
            "x": 700,
            "y": 720,
            "section_id": None,
        }

        def create():
            client = Client()
            client.force_login(LocalUserMapping.objects.get(pk=self.owner.pk))
            barrier.wait(timeout=5)
            return client.post(
                url,
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="same-concurrent-create",
                HTTP_X_BRAINSTORM_CANVAS_ID=str(self.canvas.pk),
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._thread_request, create),
                executor.submit(self._thread_request, create),
            ]
            statuses = sorted(future.result(timeout=10) for future in futures)

        self.assertEqual(statuses, [200, 201])
        self.assertEqual(
            BrainstormNode.objects.filter(
                canvas=self.canvas,
                creation_idempotency_key="same-concurrent-create",
            ).count(),
            1,
        )

    def test_same_comment_concurrent_updates_allow_only_one_writer(self):
        url = reverse(
            "prd_api:comment-item",
            kwargs={"prd_id": self.prd.pk, "comment_id": self.comment.pk},
        )
        barrier = threading.Barrier(2)

        def update(content):
            client = Client()
            client.force_login(LocalUserMapping.objects.get(pk=self.owner.pk))
            barrier.wait(timeout=5)
            return client.patch(
                url,
                data=json.dumps({"content": content, "version": 1}),
                content_type="application/json",
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._thread_request, lambda: update("코멘트 A")),
                executor.submit(self._thread_request, lambda: update("코멘트 B")),
            ]
            statuses = sorted(future.result(timeout=10) for future in futures)

        self.assertEqual(statuses, [200, 409])
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.version, 2)
        self.assertIn(self.comment.content, {"코멘트 A", "코멘트 B"})

    def test_completion_wins_before_paused_question_update(self):
        ready = threading.Event()
        release = threading.Event()
        original_describe = PrdPermissionPresenter.describe
        worker_ident = {"value": None}
        paused = {"value": False}

        def pause_first_permission_check(presenter, access):
            result = original_describe(presenter, access)
            if threading.get_ident() == worker_ident["value"] and not paused["value"]:
                paused["value"] = True
                ready.set()
                self.assertTrue(release.wait(timeout=5))
            return result

        answer_url = reverse(
            "prd_api:question-answer",
            kwargs={"prd_id": self.prd.pk, "question_id": self.question.pk},
        )
        complete_url = reverse("prd_api:complete", kwargs={"prd_id": self.prd.pk})

        def delayed_answer():
            worker_ident["value"] = threading.get_ident()
            return self.editor_client.patch(
                answer_url,
                data=json.dumps({"content": "완료 뒤 저장 시도", "version": 1}),
                content_type="application/json",
            ).status_code

        with (
            patch.object(PrdPermissionPresenter, "describe", pause_first_permission_check),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(self._thread_request, delayed_answer)
            self.assertTrue(ready.wait(timeout=5))
            completed = self.owner_client.post(
                complete_url,
                data=json.dumps({"confirm_incomplete": False}),
                content_type="application/json",
            )
            release.set()
            answer_status = future.result(timeout=10)

        self.assertEqual(completed.status_code, 200)
        self.assertEqual(answer_status, 403)
        self.question.refresh_from_db()
        self.assertEqual(self.question.answer.content, "기존 답변")

    def test_completion_wins_before_paused_brainstorm_move(self):
        ready = threading.Event()
        release = threading.Event()
        original_enforce = BrainstormAccessService.enforce_write
        worker_ident = {"value": None}
        paused = {"value": False}

        def pause_first_permission_check(access):
            original_enforce(access)
            if threading.get_ident() == worker_ident["value"] and not paused["value"]:
                paused["value"] = True
                ready.set()
                self.assertTrue(release.wait(timeout=5))

        move_url = reverse(
            "brainstorm_api:node-position",
            kwargs={"prd_id": self.prd.pk, "node_id": self.node.pk},
        )
        complete_url = reverse("prd_api:complete", kwargs={"prd_id": self.prd.pk})

        def delayed_move():
            worker_ident["value"] = threading.get_ident()
            return self.editor_client.patch(
                move_url,
                data=json.dumps({"x": 100, "y": 120, "section_id": None, "version": 1}),
                content_type="application/json",
                HTTP_X_BRAINSTORM_CANVAS_ID=str(self.canvas.pk),
            ).status_code

        with (
            patch.object(BrainstormAccessService, "enforce_write", pause_first_permission_check),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(self._thread_request, delayed_move)
            self.assertTrue(ready.wait(timeout=5))
            completed = self.owner_client.post(
                complete_url,
                data=json.dumps({"confirm_incomplete": False}),
                content_type="application/json",
            )
            release.set()
            move_status = future.result(timeout=10)

        self.assertEqual(completed.status_code, 200)
        self.assertEqual(move_status, 403)
        self.node.refresh_from_db()
        self.assertEqual((self.node.position_x, self.node.position_y), (10, 20))
        self.assertEqual(self.node.version, 1)
