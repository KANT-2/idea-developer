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

RICH_SECTION_ANSWERS = {
    1: (
        "대학생 팀 프로젝트에서 일정, 역할, 회의 결과가 여러 도구에 흩어지는 문제를 해결하는 "
        "통합 협업 서비스입니다. 팀원은 오늘 해야 할 일과 의사결정 근거를 한 화면에서 확인하고, "
        "팀장은 진행 지연을 조기에 발견할 수 있습니다. 첫 출시에서는 프로젝트 생성, 역할 분담, "
        "주간 목표, 회의 기록과 알림까지 하나의 흐름으로 제공합니다."
    ),
    2: (
        "핵심 목표는 팀원이 다음 행동을 찾는 시간을 줄이고 약속한 업무의 완료율을 높이는 것입니다. "
        "기존 메신저와 문서 도구를 대체하기보다 흩어진 결정과 실행 항목을 연결하는 데 집중합니다. "
        "사용자는 회의 직후 담당자와 마감일이 명확한 할 일을 얻고, 팀 전체는 같은 진행 상태를 공유합니다."
    ),
    3: (
        "사전 인터뷰에서 회의 내용이 채팅에 묻히고 담당자가 불명확해 일정이 반복적으로 늦어진다는 "
        "문제가 확인되었습니다. 특히 학기 중 여러 과목과 활동을 병행하는 팀은 별도 도구를 꾸준히 "
        "정리할 여유가 부족했습니다. 지금은 생성형 요약 기술과 학교 단위 협업 수요가 함께 증가해, "
        "최소 입력만으로 실행 항목을 구조화하는 경험을 검증하기 좋은 시점입니다."
    ),
    4: (
        "첫 사용자는 4~6명이 한 학기 동안 결과물을 만드는 대학생 프로젝트 팀입니다. 매주 한 번 이상 "
        "회의하고 역할이 자주 바뀌며, 팀장도 전문 프로젝트 관리자가 아닌 상황을 우선합니다. 회의 직후, "
        "마감 하루 전, 주간 회고 시점에 가장 자주 사용하며 모바일에서는 확인과 완료 처리, PC에서는 "
        "계획 편집과 회의 정리를 주로 수행합니다."
    ),
    5: (
        "핵심 문제는 정보 부족이 아니라 결정된 내용과 실제 행동이 연결되지 않는 것입니다. 회의에서 좋은 "
        "아이디어가 나와도 담당자, 기한, 완료 기준이 빠지면 실행되지 않습니다. 따라서 회의 기록에서 실행 "
        "항목을 제안하고 사용자가 확인한 뒤 팀 보드에 반영하면 누락률과 재확인 시간을 줄일 수 있다는 "
        "가설을 가장 먼저 검증합니다."
    ),
    6: (
        "MVP에는 이메일 기반 로그인, 팀 프로젝트 생성, 참여자 역할 설정, 주간 목표와 할 일 관리, 회의록 "
        "작성, 실행 항목 제안, 마감 알림과 기본 활동 기록을 포함합니다. 캘린더 양방향 동기화, 화상회의 "
        "녹음, 학교별 학사 시스템 연동, 복잡한 간트 차트와 유료 결제는 초기 범위에서 제외합니다. "
        "웹 반응형 화면을 우선 제공하고 네이티브 앱은 핵심 지표 확인 후 결정합니다."
    ),
    7: (
        "4주 파일럿에서 초대된 팀의 60% 이상이 첫 프로젝트를 만들고, 생성 팀의 50% 이상이 2주 연속 "
        "주간 목표를 갱신하는 것을 활성화 기준으로 삼습니다. 회의 후 24시간 내 실행 항목 등록률 80%, "
        "기한 내 완료율 65%, 주간 재방문율 55%를 목표로 합니다. 5개 팀의 사용 로그와 인터뷰를 함께 "
        "분석하며, 목표 미달 시 알림 빈도보다 생성 과정의 마찰과 역할 명확성을 먼저 점검합니다."
    ),
}

DEMO_PRDS = (
    {
        "slug": "campus-project-hub",
        "title": "캠퍼스 팀 프로젝트 운영 허브",
        "description": "회의의 결정 사항을 역할·일정·실행 항목으로 연결해 팀 프로젝트 완주율을 높이는 협업 서비스",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.IN_PROGRESS,
        "deadline_days": 28,
        "members": (24, 21, 22, 23, 2),
        "fill_all_questions": True,
        "answers": (),
        "comments": (
            (
                21,
                "팀장이 아니어도 회의 직후 실행 항목을 제안하고 담당자를 지정할 수 있으면 좋겠습니다.",
            ),
            (22, "모바일에서는 오늘 마감과 내가 맡은 항목이 가장 먼저 보여야 합니다."),
            (
                23,
                "완료 기준이 모호하면 체크만 하고 품질을 확인하기 어려우니 기준 입력란이 필요합니다.",
            ),
            (24, "초기 검증은 실제 수업 프로젝트 5개 팀을 대상으로 4주 동안 진행하겠습니다."),
            (
                2,
                "활성화와 재방문 지표가 구분되어 있습니다. 실행 항목 등록률의 측정 시점을 고정해 주세요.",
            ),
        ),
        "notes": (
            (
                "회의록에서 담당자·기한·완료 기준을 구조화",
                BrainstormNodeStatus.ACCEPTED,
                24,
                5,
                "yellow",
            ),
            (
                "오늘 해야 할 일과 지연 항목을 첫 화면에 표시",
                BrainstormNodeStatus.ACCEPTED,
                21,
                4,
                "blue",
            ),
            (
                "회의 종료 전 실행 항목을 팀원이 함께 확인",
                BrainstormNodeStatus.ACCEPTED,
                22,
                5,
                "green",
            ),
            ("주간 목표 달성률과 지연 원인 회고", BrainstormNodeStatus.ACCEPTED, 23, 7, "pink"),
            ("팀원별 역할과 현재 담당 업무 표시", BrainstormNodeStatus.ACCEPTED, 24, 4, "purple"),
            ("마감 하루 전 담당자 알림", BrainstormNodeStatus.ACCEPTED, 21, 6, "orange"),
            (
                "프로젝트 템플릿으로 첫 설정 시간 단축",
                BrainstormNodeStatus.ACCEPTED,
                22,
                6,
                "yellow",
            ),
            ("결정 사항 변경 이력과 근거 연결", BrainstormNodeStatus.ACCEPTED, 23, 3, "blue"),
            ("캘린더 양방향 동기화", BrainstormNodeStatus.DEFAULT, 24, None, "green"),
            ("학교 LMS 과제 일정 자동 수집", BrainstormNodeStatus.HELD, 21, None, "gray"),
        ),
    },
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

# These PRDs deliberately use real question completion flags so the dashboard
# exercises every completion-rate band.  The values are deterministic (rather
# than random at command runtime) so every teammate gets the same workspace.
DEMO_PRDS += (
    {
        "slug": "progress-24-local-market",
        "title": "동네 상권 빈자리 알림",
        "description": "자주 찾는 매장의 한산한 시간을 알려주는 지역 생활 서비스",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.IN_PROGRESS,
        "deadline_days": 35,
        "creator_id": 21,
        "members": (21, 24, 22, 2),
        "member_roles": {24: PrdParticipantRole.EDITOR, 2: PrdParticipantRole.TUTOR},
        "target_completion_rate": 24,
        "answers": (),
        "comments": ((24, "알림 기준을 사용자가 직접 조절할 수 있어야 합니다."),),
        "notes": (
            ("혼잡도 대신 예상 대기 시간을 표시", BrainstormNodeStatus.ACCEPTED, 24, 1, "yellow"),
            ("즐겨찾는 매장만 알림 받기", BrainstormNodeStatus.DEFAULT, 22, None, "blue"),
        ),
    },
    {
        "slug": "progress-32-reading-club",
        "title": "온라인 독서모임 운영 도구",
        "description": "발제와 토론 기록을 한곳에 모아 모임 참여를 돕는 서비스",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.HELD,
        "deadline_days": 42,
        "creator_id": 22,
        "members": (22, 24, 23, 25),
        "member_roles": {24: PrdParticipantRole.VIEWER},
        "target_completion_rate": 32,
        "answers": (),
        "comments": ((23, "지난 모임의 핵심 질문을 다음 모임과 연결하면 좋겠습니다."),),
        "notes": (
            ("책별 발제 질문 템플릿", BrainstormNodeStatus.ACCEPTED, 23, 2, "green"),
            ("모임 종료 후 한 줄 회고", BrainstormNodeStatus.DEFAULT, 25, None, "pink"),
        ),
    },
    {
        "slug": "progress-46-campus-meal",
        "title": "캠퍼스 식단 추천",
        "description": "시간과 취향에 맞는 교내 식당 메뉴를 빠르게 고르는 서비스",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.IN_PROGRESS,
        "deadline_days": 21,
        "creator_id": 23,
        "members": (23, 24, 21, 26),
        "member_roles": {24: PrdParticipantRole.EDITOR},
        "target_completion_rate": 46,
        "answers": (),
        "comments": ((24, "수업 종료 위치와 다음 수업까지 남은 시간을 함께 고려해 주세요."),),
        "notes": (
            ("이동 시간을 반영한 식당 추천", BrainstormNodeStatus.ACCEPTED, 24, 4, "orange"),
            ("알레르기 메뉴 제외", BrainstormNodeStatus.ACCEPTED, 26, 5, "yellow"),
        ),
    },
    {
        "slug": "progress-54-volunteer-match",
        "title": "주말 봉사활동 매칭",
        "description": "관심 분야와 이동 거리로 참여 가능한 봉사활동을 찾는 서비스",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.IN_PROGRESS,
        "deadline_days": 18,
        "creator_id": 25,
        "members": (25, 24, 27, 2),
        "member_roles": {24: PrdParticipantRole.VIEWER, 2: PrdParticipantRole.TUTOR},
        "target_completion_rate": 54,
        "answers": (),
        "comments": ((27, "신청 마감 여부를 목록에서 바로 확인하고 싶습니다."),),
        "notes": (
            ("대중교통 이동 시간 필터", BrainstormNodeStatus.ACCEPTED, 27, 4, "blue"),
            ("활동 전 준비물 체크", BrainstormNodeStatus.DEFAULT, 25, None, "green"),
        ),
    },
    {
        "slug": "progress-66-shared-budget",
        "title": "소모임 공동 예산 관리",
        "description": "회비 사용 내역과 남은 예산을 구성원이 함께 확인하는 서비스",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.IN_PROGRESS,
        "deadline_days": 16,
        "creator_id": 26,
        "members": (26, 24, 28, 29),
        "member_roles": {24: PrdParticipantRole.EDITOR},
        "target_completion_rate": 66,
        "answers": (),
        "comments": ((24, "지출 증빙과 승인 상태가 한 화면에서 보여야 합니다."),),
        "notes": (
            ("영수증 사진으로 지출 초안 생성", BrainstormNodeStatus.ACCEPTED, 24, 6, "purple"),
            ("월별 예산 초과 경고", BrainstormNodeStatus.ACCEPTED, 28, 7, "pink"),
        ),
    },
    {
        "slug": "progress-73-study-room",
        "title": "스터디룸 예약 도우미",
        "description": "팀 일정과 위치를 비교해 적합한 스터디 공간을 추천하는 서비스",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.HELD,
        "deadline_days": 30,
        "creator_id": 27,
        "members": (27, 24, 29, 30),
        "member_roles": {24: PrdParticipantRole.VIEWER},
        "target_completion_rate": 73,
        "answers": (),
        "comments": ((29, "예약 취소 수수료와 운영 시간을 함께 비교해 주세요."),),
        "notes": (
            ("팀원 중간 지점 추천", BrainstormNodeStatus.ACCEPTED, 29, 4, "yellow"),
            ("화이트보드 등 시설 필터", BrainstormNodeStatus.DEFAULT, 30, None, "orange"),
        ),
    },
    {
        "slug": "progress-85-career-log",
        "title": "프로젝트 경험 정리 노트",
        "description": "활동 기록을 포트폴리오 문장으로 발전시키는 커리어 기록 서비스",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.IN_PROGRESS,
        "deadline_days": 12,
        "creator_id": 28,
        "members": (28, 24, 21, 2),
        "member_roles": {24: PrdParticipantRole.EDITOR, 2: PrdParticipantRole.TUTOR},
        "target_completion_rate": 85,
        "answers": (),
        "comments": ((24, "성과 문장에는 행동과 수치 근거를 함께 남기면 좋겠습니다."),),
        "notes": (
            ("주간 활동에서 성과 후보 추출", BrainstormNodeStatus.ACCEPTED, 24, 3, "green"),
            ("면접 질문별 경험 연결", BrainstormNodeStatus.ACCEPTED, 21, 5, "blue"),
        ),
    },
    {
        "slug": "progress-93-event-checkin",
        "title": "교내 행사 체크인 개선",
        "description": "대기 시간을 줄이고 현장 운영 상태를 공유하는 행사 체크인 서비스",
        "prd_type": PrdType.NEW_PRODUCT,
        "status": PrdStatus.IN_PROGRESS,
        "deadline_days": 9,
        "creator_id": 29,
        "members": (29, 24, 22, 30),
        "member_roles": {24: PrdParticipantRole.VIEWER},
        "target_completion_rate": 93,
        "answers": (),
        "comments": ((30, "네트워크가 불안정한 현장에서도 체크인이 이어져야 합니다."),),
        "notes": (
            ("오프라인 체크인 후 재연결 동기화", BrainstormNodeStatus.ACCEPTED, 30, 6, "purple"),
            ("시간대별 입장 인원 예측", BrainstormNodeStatus.ACCEPTED, 22, 7, "pink"),
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
                creator_user_id = spec.get("creator_id", OWNER_ID)
                prd, created = service.create(
                    CreatePrdCommand(
                        title=spec["title"],
                        description=spec["description"],
                        deadline=timezone.localdate() + timedelta(days=spec["deadline_days"]),
                        prd_type=spec["prd_type"],
                        round_id=None,
                        team_id=None,
                        creator_user_id=creator_user_id,
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
        actor_user_id = spec.get("creator_id", OWNER_ID)
        participants = {row.user_id: row for row in prd.participants.all()}
        member_roles = dict(spec.get("member_roles", {}))
        if 2 in participants:
            member_roles.setdefault(2, PrdParticipantRole.TUTOR)
        for user_id, role in member_roles.items():
            participant = participants.get(user_id)
            if participant is not None and participant.role != PrdParticipantRole.OWNER:
                participant.role = role
                participant.save(update_fields=["role"])

        questions = list(prd.sections.order_by("position", "id").prefetch_related("questions"))
        flat_questions = [
            question
            for section in questions
            for question in section.questions.all().order_by("position", "id")
        ]
        answers = spec["answers"]
        if spec.get("fill_all_questions"):
            answers = tuple(
                Command._rich_answer(section=section, question=question)
                for section in questions
                for question in section.questions.all().order_by("position", "id")
            )
        elif target_rate := spec.get("target_completion_rate"):
            completed_count = round(len(flat_questions) * target_rate / 100)
            answers = tuple(
                Command._progress_answer(question=question, index=index)
                for index, question in enumerate(flat_questions[:completed_count], start=1)
            )
        for question, answer in zip(flat_questions, answers, strict=False):
            PrdAnswer.objects.create(
                question=question,
                content=answer,
                updated_by_user_id=actor_user_id,
            )
            question.is_completed = True
            question.save(update_fields=["is_completed", "updated_at"])
            PrdChangeHistory.objects.create(
                prd=prd,
                actor_user_id=actor_user_id,
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
                actor_user_id=actor_user_id,
                event_type="prd_completed",
                after_data={"status": PrdStatus.COMPLETED},
            )

    @staticmethod
    def _rich_answer(*, section, question):
        base = RICH_SECTION_ANSWERS.get(section.position, RICH_SECTION_ANSWERS[1])
        return (
            f"{base}\n\n"
            f"질문별 확인 사항: ‘{question.prompt}’에 대해서는 사용자 인터뷰, 실제 사용 로그와 "
            "주간 회고 결과를 함께 근거로 판단합니다. 담당자는 매주 금요일 수치를 확인하고, 목표 대비 "
            "차이가 15%p 이상이면 원인을 기록한 뒤 다음 주 실험 범위와 우선순위를 조정합니다."
        )

    @staticmethod
    def _progress_answer(*, question, index):
        return (
            f"검토 완료 항목 {index}: {question.prompt} "
            "사용자 관찰과 팀 논의를 바탕으로 현재 가설과 검증 기준을 정리했습니다. "
            "다음 실험에서 확인할 지표와 담당자를 지정하고 결과에 따라 내용을 보완합니다."
        )
