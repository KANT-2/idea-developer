from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.brainstorm.models import (
    BrainstormCanvas,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)
from apps.integration.repository import get_default_integration_repository
from apps.prds.models import (
    PrdAnswer,
    PrdChangeHistory,
    PrdComment,
    PrdCommentType,
    PrdParticipantRole,
    PrdStatus,
    PrdType,
)
from apps.prds.services import CreatePrdCommand, PrdCreationService

DEMO_PREFIX = "roundless-demo-v1"
OWNER_ID = 24

DEMO_PRDS = (
    {
        "slug": "learning-coach",
        "title": "AI 학습 루틴 코치",
        "description": "매일의 학습 목표와 회고를 연결해 꾸준한 성장을 돕는 서비스",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.IN_PROGRESS,
        "deadline_days": 14,
        "members": (24, 21, 22, 23, 2),
        "answers": (
            "학습 계획을 꾸준히 실행하기 어려운 사용자가 매일 목표와 회고를 "
            "한곳에서 관리하도록 돕습니다.",
            "4주 재방문율과 주간 목표 완료율을 핵심 지표로 확인합니다.",
            "목표 설정, 완료 체크, 회고 작성까지 한 흐름으로 연결합니다.",
            "AI 추천은 사용자가 입력한 학습 기록을 바탕으로 선택적으로 제공합니다.",
        ),
        "comments": (
            (21, "첫 화면에서 오늘의 목표를 바로 입력할 수 있으면 좋겠습니다."),
            (22, "주간 회고에는 달성률과 실패 원인을 함께 보여주세요."),
            (2, "성공 지표를 측정 가능한 수치로 더 구체화해 보세요."),
        ),
        "notes": (
            ("하루 학습 목표는 최대 3개로 제한", BrainstormNodeStatus.ACCEPTED, 21, 1, "yellow"),
            (
                "완료한 목표를 주간 회고 그래프로 시각화",
                BrainstormNodeStatus.ACCEPTED,
                22,
                2,
                "blue",
            ),
            (
                "목표 미달성 이유를 한 문장으로 기록",
                BrainstormNodeStatus.DEFAULT,
                23,
                None,
                "green",
            ),
            ("알림 빈도를 사용자가 직접 조절", BrainstormNodeStatus.ACCEPTED, 24, 3, "pink"),
            ("AI가 다음 날 목표 난이도를 추천", BrainstormNodeStatus.ACCEPTED, 24, 3, "purple"),
            ("친구와 학습 랭킹 경쟁", BrainstormNodeStatus.HELD, 21, None, "gray"),
        ),
    },
    {
        "slug": "interview-insights",
        "title": "사용자 인터뷰 인사이트 자동 분류",
        "description": "인터뷰 메모를 주제별로 묶고 제품 기회로 전환하는 협업 기능",
        "prd_type": PrdType.NEW_FEATURE,
        "status": PrdStatus.COMPLETED,
        "deadline_days": -3,
        "members": (24, 25, 26, 27, 2),
        "answers": (
            "인터뷰 결과를 수작업으로 정리하면서 중요한 반복 의견이 누락되는 문제를 해결합니다.",
            "분류 정확도와 인사이트 정리 시간을 함께 측정합니다.",
            "원문 근거를 유지하면서 유사 의견을 주제별 카드로 묶습니다.",
            "사용자가 분류 결과를 검토하고 수정한 뒤 확정할 수 있습니다.",
            "각 인사이트에는 출처 인터뷰와 근거 문장을 표시합니다.",
            "외부 인터뷰 도구 자동 동기화는 이번 범위에서 제외합니다.",
        ),
        "comments": (
            (25, "분류 결과에 원문 근거 문장을 같이 표시해야 신뢰할 수 있습니다."),
            (26, "여러 인터뷰에서 반복된 의견은 빈도 배지를 붙이면 좋겠습니다."),
            (2, "완료본의 근거 연결이 명확합니다. 다음 버전에서 정확도 측정을 보완해 주세요."),
        ),
        "notes": (
            ("인터뷰 원문과 요약을 나란히 표시", BrainstormNodeStatus.ACCEPTED, 25, 1, "yellow"),
            ("유사 의견을 주제 카드로 자동 묶기", BrainstormNodeStatus.ACCEPTED, 26, 2, "blue"),
            ("각 인사이트에 출처 인터뷰 연결", BrainstormNodeStatus.ACCEPTED, 27, 2, "green"),
            (
                "팀원이 분류 결과를 수정할 수 있어야 함",
                BrainstormNodeStatus.ACCEPTED,
                24,
                3,
                "pink",
            ),
            ("반복 의견에 빈도 배지 표시", BrainstormNodeStatus.ACCEPTED, 25, 3, "purple"),
        ),
    },
    {
        "slug": "idea-board",
        "title": "팀 아이디어 보드 개선",
        "description": "산발적인 아이디어를 빠르게 정리하고 우선순위를 합의하는 보드 개선안",
        "prd_type": PrdType.IMPROVEMENT,
        "status": PrdStatus.HELD,
        "deadline_days": 25,
        "members": (24, 28, 29, 30),
        "answers": (
            "회의 중 나온 아이디어가 흩어져 우선순위 합의가 늦어지는 문제를 개선합니다.",
            "아이디어 정리 시간과 회의 후 결정 완료율을 측정합니다.",
        ),
        "comments": (
            (28, "투표 전에 아이디어를 익명으로 보면 선입견을 줄일 수 있습니다."),
            (29, "우선순위 기준을 사용자 가치와 구현 난이도로 나눠보면 좋겠습니다."),
            (24, "다음 회의에서 투표 방식과 정렬 기준을 먼저 확정하겠습니다."),
        ),
        "notes": (
            ("드래그로 아이디어 우선순위 변경", BrainstormNodeStatus.DEFAULT, 28, None, "yellow"),
            ("가치 대비 난이도 2축 보기", BrainstormNodeStatus.ACCEPTED, 29, 2, "blue"),
            ("회의 전 익명 투표 모드", BrainstormNodeStatus.DEFAULT, 30, None, "green"),
            ("유사 아이디어 자동 병합", BrainstormNodeStatus.HELD, 24, None, "gray"),
        ),
    },
    {
        "slug": "personal-onboarding",
        "title": "신규 팀원 온보딩 체크리스트",
        "description": "첫 일주일에 꼭 알아야 할 업무와 자료를 빠짐없이 안내하는 개인 기획",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.IN_PROGRESS,
        "deadline_days": 7,
        "members": (24,),
        "answers": (
            "새 팀원이 첫 주에 필요한 계정과 자료를 놓치지 않도록 안내합니다.",
            "첫 주 체크리스트 완료율을 핵심 지표로 확인합니다.",
            "첫날, 첫 주, 첫 달 단위로 해야 할 일을 구분합니다.",
        ),
        "comments": ((24, "첫날·첫 주·첫 달 단위로 체크리스트를 나누어 작성하겠습니다."),),
        "notes": (
            ("첫날 필수 계정과 도구 안내", BrainstormNodeStatus.ACCEPTED, 24, 1, "yellow"),
            ("첫 주에 만날 동료 목록 제공", BrainstormNodeStatus.DEFAULT, 24, None, "blue"),
            ("30일 목표를 리더와 함께 작성", BrainstormNodeStatus.ACCEPTED, 24, 3, "green"),
        ),
    },
    {
        "slug": "meeting-reminder",
        "title": "회의 액션 아이템 리마인더",
        "description": "회의 후 담당자와 기한을 자동으로 정리해 알림을 보내는 개인 개선안",
        "prd_type": PrdType.IMPROVEMENT,
        "status": PrdStatus.DROPPED,
        "deadline_days": 5,
        "members": (24,),
        "answers": ("회의 후 담당자와 기한이 누락되는 문제를 줄이는 기능입니다.",),
        "comments": ((24, "기존 협업 도구와 기능이 겹쳐 현재 버전에서는 중단합니다."),),
        "notes": (
            ("회의록에서 담당자와 기한 추출", BrainstormNodeStatus.ACCEPTED, 24, 1, "yellow"),
            ("마감 하루 전 개인 알림", BrainstormNodeStatus.DEFAULT, 24, None, "blue"),
            ("슬랙과 이메일 동시 알림", BrainstormNodeStatus.HELD, 24, None, "gray"),
        ),
    },
)


class Command(BaseCommand):
    help = "부모 VIEW 사용자를 참조하는 공용 PRD·브레인스토밍 데모 데이터를 생성합니다."

    def handle(self, *args, **options):
        repository = get_default_integration_repository()
        required_user_ids = tuple(
            sorted({user_id for spec in DEMO_PRDS for user_id in spec["members"]})
        )
        invalid = [
            user_id
            for user_id in required_user_ids
            if (user := repository.get_user(user_id)) is None
            or not user.is_active
            or user.approval_status != settings.INTEGRATION_APPROVED_USER_STATUS
        ]
        if invalid:
            raise CommandError(
                "부모 VIEW에서 활성·승인 사용자를 찾지 못했습니다: " + ", ".join(map(str, invalid))
            )

        created_count = 0
        skipped_count = 0
        with transaction.atomic():
            service = PrdCreationService(repository)
            for spec in DEMO_PRDS:
                prd, created = service.create(
                    CreatePrdCommand(
                        title=spec["title"],
                        description=spec["description"],
                        deadline=timezone.localdate() + timedelta(days=spec["deadline_days"]),
                        prd_type=spec["prd_type"],
                        round_id=None,
                        team_id=None,
                        creator_user_id=OWNER_ID,
                        idempotency_key=f"{DEMO_PREFIX}:{spec['slug']}",
                        participant_user_ids=spec["members"],
                    )
                )
                if not created:
                    skipped_count += 1
                    continue
                created_count += 1
                self._fill_prd(prd, spec)

        self.stdout.write(
            self.style.SUCCESS(
                f"데모 워크스페이스 준비 완료: 생성 {created_count}개, 기존 유지 {skipped_count}개"
            )
        )

    @staticmethod
    def _fill_prd(prd, spec):
        now = timezone.now()
        participants = {row.user_id: row for row in prd.participants.all()}
        if 2 in participants:
            participants[2].role = PrdParticipantRole.TUTOR
            participants[2].save(update_fields=["role"])

        questions = list(prd.sections.order_by("position", "id").prefetch_related("questions"))
        flat_questions = [
            question
            for section in questions
            for question in section.questions.all().order_by("position", "id")
        ]
        for question, answer in zip(flat_questions, spec["answers"], strict=False):
            PrdAnswer.objects.create(
                question=question,
                content=answer,
                updated_by_user_id=OWNER_ID,
            )
            question.is_completed = True
            question.save(update_fields=["is_completed", "updated_at"])
            PrdChangeHistory.objects.create(
                prd=prd,
                actor_user_id=OWNER_ID,
                event_type="answer_updated",
                after_data={"question_id": question.id, "content": answer},
            )

        comment_target = flat_questions[0] if flat_questions else None
        for author_id, content in spec["comments"]:
            role = participants[author_id].role
            is_tutor = role == PrdParticipantRole.TUTOR
            PrdComment.objects.create(
                prd=prd,
                section_question=comment_target,
                author_user_id=author_id,
                author_role_at_created=role,
                comment_type=(PrdCommentType.GUIDANCE if is_tutor else PrdCommentType.GENERAL),
                content=content,
                is_contribution_eligible=not is_tutor,
            )

        canvas = BrainstormCanvas.objects.create(
            prd=prd,
            creation_idempotency_key=f"{DEMO_PREFIX}:{spec['slug']}:canvas",
        )
        nodes = []
        sections_by_position = {section.position: section for section in questions}
        for index, (content, status, author_id, section_position, color) in enumerate(
            spec["notes"]
        ):
            section = sections_by_position.get(section_position)
            nodes.append(
                BrainstormNode.objects.create(
                    canvas=canvas,
                    node_type=BrainstormNodeType.NOTE,
                    content=content,
                    creation_idempotency_key=(f"{DEMO_PREFIX}:{spec['slug']}:node:{index}"),
                    color=color,
                    position_x=Decimal(90 + (index % 3) * 280),
                    position_y=Decimal(110 + (index // 3) * 210),
                    section=section,
                    author_id=author_id,
                    assignee_id=author_id,
                    status=status,
                )
            )
        connectable = [node for node in nodes if node.status == BrainstormNodeStatus.ACCEPTED]
        for index, (node_a, node_b) in enumerate(zip(connectable, connectable[1:], strict=False)):
            BrainstormConnection.objects.create(
                canvas=canvas,
                node_a=node_a,
                node_b=node_b,
                creation_idempotency_key=(f"{DEMO_PREFIX}:{spec['slug']}:connection:{index}"),
            )
            if index == 1:
                break

        prd.status = spec["status"]
        prd.completed_at = now if spec["status"] == PrdStatus.COMPLETED else None
        prd.save(update_fields=["status", "completed_at", "updated_at"])
        if spec["status"] == PrdStatus.COMPLETED:
            PrdChangeHistory.objects.create(
                prd=prd,
                actor_user_id=OWNER_ID,
                event_type="prd_completed",
                after_data={"status": PrdStatus.COMPLETED},
            )
