from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import ceil

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import (
    Avg,
    Case,
    Count,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Value,
    When,
    Window,
)
from django.db.models.functions import RowNumber, TruncDate
from django.utils import timezone

from apps.accounts.permissions import ParticipantAction, role_permission_policy
from apps.ai.models import AiActionType, AiFeatureType, AiUsageLog, AiUsageStatus
from apps.integration.context import IntegrationContext, is_admin_context, is_tutor_context
from apps.integration.repository import IntegrationRepository

from .models import (
    Prd,
    PrdChangeHistory,
    PrdParticipant,
    PrdParticipantRole,
    PrdStatus,
    PrdType,
)
from .status_services import PrdStatusService

HOME_TABS = {"all", "project", "team", "personal"}
HOME_SCOPES = {"all", "mine", "viewer"}
TUTOR_PROJECT_SCOPES = {"all", "round_team", "team", "personal"}
TUTOR_DASHBOARD_VIEWS = {"tutoring", "editing"}
HOME_SORTS = {
    "default",
    "deadline_asc",
    "completion_desc",
    "updated_desc",
    "ai_coaching_desc",
}


@dataclass(frozen=True, slots=True)
class HomeFilters:
    scope: str = "all"
    tab: str = "all"
    statuses: tuple[str, ...] = ()
    prd_types: tuple[str, ...] = ()
    deadline_from: date | None = None
    deadline_to: date | None = None
    participant_user_id: int | None = None
    team_id: int | None = None
    round_scope: str = "all"
    project_scope: str = "all"
    dashboard_view: str = "tutoring"
    sort: str = "default"
    page: int = 1
    page_size: int = 12

    def validate(self, *, context: IntegrationContext):
        errors = {}
        if self.scope not in HOME_SCOPES:
            errors["scope"] = "지원하지 않는 PRD 조회 범위입니다."
        if self.tab not in HOME_TABS:
            errors["tab"] = "지원하지 않는 탭입니다."
        invalid_statuses = set(self.statuses) - set(PrdStatus.values)
        if invalid_statuses:
            errors["status"] = "지원하지 않는 PRD 상태가 포함되어 있습니다."
        invalid_types = set(self.prd_types) - set(PrdType.values)
        if invalid_types:
            errors["prd_type"] = "지원하지 않는 PRD 유형이 포함되어 있습니다."
        if self.sort not in HOME_SORTS:
            errors["sort"] = "지원하지 않는 정렬 방식입니다."
        if self.deadline_from and self.deadline_to and self.deadline_from > self.deadline_to:
            errors["deadline"] = "마감일 시작일은 종료일보다 늦을 수 없습니다."
        if self.page <= 0 or self.page_size <= 0:
            errors["pagination"] = "페이지 값은 1 이상이어야 합니다."
        if self.participant_user_id is not None and self.participant_user_id <= 0:
            errors["participant_user_id"] = "참여자 ID가 올바르지 않습니다."
        if self.team_id is not None and self.team_id != context.team_id:
            raise PermissionDenied("Another round team cannot be queried.")
        if self.round_scope not in {"all", "none"}:
            try:
                if int(self.round_scope) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors["round_scope"] = "회차 필터 값이 올바르지 않습니다."
        if self.project_scope not in TUTOR_PROJECT_SCOPES:
            errors["project_scope"] = "지원하지 않는 프로젝트 구분입니다."
        if self.dashboard_view not in TUTOR_DASHBOARD_VIEWS:
            errors["dashboard_view"] = "지원하지 않는 튜터 화면입니다."
        if errors:
            raise ValidationError(errors)


class HomeQueryService:
    def __init__(self, repository: IntegrationRepository):
        self.repository = repository

    def get_home(self, *, context: IntegrationContext, filters: HomeFilters):
        filters.validate(context=context)
        today = timezone.localdate()
        tutor_mode = self.is_tutor_context(context)
        tutor_management_mode = tutor_mode and filters.dashboard_view == "tutoring"
        base = self._dashboard_base(
            context=context,
            tutor_mode=tutor_mode,
            dashboard_view=filters.dashboard_view,
        )
        PrdStatusService().complete_overdue(
            prd_ids=base.values_list("id", flat=True),
            today=today,
        )
        base = self._dashboard_base(
            context=context,
            tutor_mode=tutor_mode,
            dashboard_view=filters.dashboard_view,
        )
        kpis = self._get_kpis(base=base, today=today)
        queryset = self._apply_filters(
            base.with_home_metrics(user_id=context.user_id),
            filters=filters,
            context=context,
            tutor_mode=tutor_management_mode,
        )
        queryset = self._apply_sort(queryset, filters.sort)
        total_items = queryset.count()
        offset = (filters.page - 1) * filters.page_size
        page_prds = list(queryset[offset : offset + filters.page_size])
        participants_by_prd = self._card_participants(prds=page_prds)
        weekly_activity, recent_activity = self._get_activity(
            base=base,
            context=context,
            today=today,
        )
        current_user = None
        if context.round_id is not None:
            current_user = self.repository.get_round_user_summaries(
                user_ids=(context.user_id,),
                round_id=context.round_id,
            ).get(context.user_id)
        else:
            current_user = self.repository.get_user_summaries(
                user_ids=(context.user_id,),
            ).get(context.user_id)
        return {
            "dashboard_mode": "tutor" if tutor_mode else "standard",
            "dashboard_view": filters.dashboard_view if tutor_mode else "editing",
            "user": {
                "id": context.user_id,
                "display_name": (
                    current_user.display_name if current_user else f"사용자 {context.user_id}"
                ),
            },
            "kpis": kpis,
            "weekly_activity": weekly_activity,
            "recent_activity": recent_activity["items"],
            "recent_activity_pagination": recent_activity["pagination"],
            "applied_filters": self._serialize_filters(filters),
            "filter_options": self._filter_options(base=base, context=context),
            "items": [
                self._serialize_card(
                    prd=prd,
                    participants=participants_by_prd.get(prd.id, []),
                    today=today,
                    context=context,
                    tutor_mode=tutor_management_mode,
                )
                for prd in page_prds
            ],
            "pagination": {
                "page": filters.page,
                "page_size": filters.page_size,
                "total_items": total_items,
                "total_pages": ceil(total_items / filters.page_size) if total_items else 0,
            },
        }

    @staticmethod
    def is_tutor_context(context: IntegrationContext) -> bool:
        return is_tutor_context(context)

    @staticmethod
    def _dashboard_base(
        *,
        context: IntegrationContext,
        tutor_mode: bool,
        dashboard_view: str = "tutoring",
    ):
        participant = PrdParticipant.objects.filter(
            prd_id=OuterRef("pk"),
            user_id=context.user_id,
        )
        queryset = Prd.objects.active().annotate(_is_participant=Exists(participant))
        if tutor_mode:
            tutor_participation = participant.filter(role=PrdParticipantRole.TUTOR)
            if dashboard_view == "tutoring":
                return queryset.annotate(_is_tutor_participant=Exists(tutor_participation)).filter(
                    _is_tutor_participant=True
                )
            editing_participation = participant.filter(
                role__in=(
                    PrdParticipantRole.OWNER,
                    PrdParticipantRole.EDITOR,
                )
            )
            return queryset.annotate(_is_editing_participant=Exists(editing_participation)).filter(
                _is_editing_participant=True
            )
        if context.round_id is not None and context.team_id is not None:
            return queryset.filter(
                Q(_is_participant=True)
                | Q(
                    round_id=context.round_id,
                    team_id=context.team_id,
                    is_team_shared=True,
                )
            )
        return queryset.filter(_is_participant=True)

    def _filter_options(self, *, base, context: IntegrationContext):
        rounds = []
        round_ids = list(
            base.exclude(round_id__isnull=True)
            .order_by("-round_id")
            .values_list("round_id", flat=True)
            .distinct()
        )
        for round_id in round_ids:
            membership = self.repository.get_membership(context.user_id, round_id)
            rounds.append(
                {
                    "id": round_id,
                    "title": membership.round_title if membership else f"회차 #{round_id}",
                }
            )
        return {
            "rounds": rounds,
            "has_roundless": base.filter(round_id__isnull=True).exists(),
            "project_scopes": ["round_team", "team", "personal"],
        }

    def get_tutor_students(
        self,
        *,
        context: IntegrationContext,
        query: str,
        page: int,
        page_size: int,
        round_scope: str = "all",
        project_scope: str = "all",
    ):
        if not self.is_tutor_context(context):
            raise PermissionDenied("Tutor project access is required.")
        normalized_query = query.strip()
        errors = {}
        if len(normalized_query) < 2:
            errors["q"] = "학생 이름을 2자 이상 입력해 주세요."
        if len(normalized_query) > 100:
            errors["q"] = "학생 이름 검색어는 100자 이하여야 합니다."
        if page <= 0 or page_size <= 0:
            errors["pagination"] = "페이지 값은 1 이상이어야 합니다."
        if errors:
            raise ValidationError(errors)

        filters = HomeFilters(round_scope=round_scope, project_scope=project_scope)
        filters.validate(context=context)
        base = self._apply_project_filters(
            self._dashboard_base(
                context=context,
                tutor_mode=True,
                dashboard_view="tutoring",
            ).with_home_metrics(user_id=context.user_id),
            filters=filters,
        )
        candidate_rows = list(
            PrdParticipant.objects.filter(
                prd_id__in=base.values("id"),
                role=PrdParticipantRole.EDITOR,
            )
            .exclude(user_id=context.user_id)
            .values("user_id")
            .annotate(project_count=Count("prd_id", distinct=True))
            .order_by("user_id")
        )
        candidate_ids = tuple(row["user_id"] for row in candidate_rows)
        summaries = {}
        selected_round_id = int(round_scope) if round_scope not in {"all", "none"} else None
        summary_round_id = (
            selected_round_id
            if selected_round_id is not None
            else context.round_id
            if round_scope == "all"
            else None
        )
        if summary_round_id is not None:
            summaries.update(
                self.repository.get_round_user_summaries(
                    user_ids=candidate_ids,
                    round_id=summary_round_id,
                )
            )
        missing_ids = tuple(user_id for user_id in candidate_ids if user_id not in summaries)
        if missing_ids:
            summaries.update(self.repository.get_user_summaries(user_ids=missing_ids))

        matching = []
        folded_query = normalized_query.casefold()
        for row in candidate_rows:
            summary = summaries.get(row["user_id"])
            display_name = summary.display_name if summary else f"사용자 {row['user_id']}"
            if folded_query not in display_name.casefold():
                continue
            matching.append(
                {
                    "user_id": row["user_id"],
                    "display_name": display_name,
                    "project_count": row["project_count"],
                }
            )
        matching.sort(key=lambda row: (row["display_name"].casefold(), row["user_id"]))
        name_counts = {}
        for row in matching:
            key = row["display_name"].casefold()
            name_counts[key] = name_counts.get(key, 0) + 1

        total_items = len(matching)
        offset = (page - 1) * page_size
        items = matching[offset : offset + page_size]
        for row in items:
            duplicate = name_counts[row["display_name"].casefold()] > 1
            row["has_duplicate_name"] = duplicate
            row["email"] = None
            if duplicate:
                parent_user = self.repository.get_user(row["user_id"])
                if parent_user:
                    row["email"] = parent_user.primary_email or parent_user.user_email
        return {
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": ceil(total_items / page_size) if total_items else 0,
            },
        }

    def _get_activity(self, *, base, context: IntegrationContext, today):
        """Return activity only from PRDs where the current user is a participant."""
        participant_prd_ids = base.filter(
            participants__user_id=context.user_id,
        ).values("id")
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        daily_counts = {
            row["day"]: row["count"]
            for row in (
                PrdChangeHistory.objects.filter(
                    prd_id__in=participant_prd_ids,
                    actor_user_id=context.user_id,
                    created_at__date__range=(week_start, week_end),
                )
                .annotate(day=TruncDate("created_at"))
                .values("day")
                .annotate(count=Count("id"))
                .order_by("day")
            )
        }
        day_labels = ("월", "화", "수", "목", "금", "토", "일")
        weekly = [
            {
                "date": (week_start + timedelta(days=offset)).isoformat(),
                "day_label": day_labels[offset],
                "count": daily_counts.get(week_start + timedelta(days=offset), 0),
            }
            for offset in range(7)
        ]

        recent = self._recent_activity_page(
            participant_prd_ids=participant_prd_ids,
            page=1,
            page_size=5,
        )
        return weekly, recent

    def get_recent_activity(
        self,
        *,
        context: IntegrationContext,
        page: int,
        page_size: int,
    ):
        if page <= 0 or page_size <= 0:
            raise ValidationError({"pagination": "페이지 값은 1 이상이어야 합니다."})
        base = self._dashboard_base(
            context=context,
            tutor_mode=self.is_tutor_context(context),
        )
        participant_prd_ids = base.filter(
            participants__user_id=context.user_id,
        ).values("id")
        return self._recent_activity_page(
            participant_prd_ids=participant_prd_ids,
            page=page,
            page_size=page_size,
        )

    def _recent_activity_page(self, *, participant_prd_ids, page, page_size):
        queryset = (
            PrdChangeHistory.objects.filter(prd_id__in=participant_prd_ids)
            .select_related("prd")
            .order_by("-created_at", "-id")
        )
        total_items = queryset.count()
        offset = (page - 1) * page_size
        histories = list(queryset[offset : offset + page_size])
        names = self._activity_actor_names(histories)
        return {
            "items": [
                {
                    "id": history.id,
                    "prd_id": history.prd_id,
                    "prd_title": history.prd.title,
                    "actor_user_id": history.actor_user_id,
                    "actor_display_name": names.get(
                        (history.prd.round_id, history.actor_user_id),
                        f"사용자 {history.actor_user_id}",
                    ),
                    "event_type": history.event_type,
                    "description": self._activity_description(history),
                    "created_at": history.created_at.isoformat(),
                }
                for history in histories
            ],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": ceil(total_items / page_size) if total_items else 0,
            },
        }

    def _activity_actor_names(self, histories):
        user_ids_by_round = {}
        for history in histories:
            user_ids_by_round.setdefault(history.prd.round_id, set()).add(history.actor_user_id)
        names = {}
        for round_id, user_ids in user_ids_by_round.items():
            if round_id is None:
                summaries = self.repository.get_user_summaries(
                    user_ids=tuple(user_ids),
                )
            else:
                summaries = self.repository.get_round_user_summaries(
                    user_ids=tuple(user_ids),
                    round_id=round_id,
                )
            for user_id, summary in summaries.items():
                names[(round_id, user_id)] = summary.display_name
        return names

    @staticmethod
    def _activity_description(history):
        labels = {
            "answer_updated": "질문 답변을 수정했습니다.",
            "participant_added": "참여자를 추가했습니다.",
            "participant_role_changed": "참여자 역할을 변경했습니다.",
            "participant_removed": "참여자를 제외했습니다.",
            "prd_created": "새 PRD를 만들었습니다.",
            "comment_created": "새 코멘트를 작성했습니다.",
            "prd_completed": "PRD를 완료했습니다.",
            "prd_reopened": "PRD를 다시 열었습니다.",
        }
        if history.event_type == "question_hold_changed":
            return (
                "질문을 보류했습니다."
                if history.after_data.get("is_held")
                else "질문 보류를 해제했습니다."
            )
        return labels.get(history.event_type, "PRD를 업데이트했습니다.")

    @staticmethod
    def _get_kpis(*, base, today):
        due_end = today + timedelta(days=6)
        counts = base.aggregate(
            total_prds=Count("id", distinct=True),
            in_progress_prds=Count("id", filter=Q(status=PrdStatus.IN_PROGRESS), distinct=True),
            completed_prds=Count("id", filter=Q(status=PrdStatus.COMPLETED), distinct=True),
            held_prds=Count("id", filter=Q(status=PrdStatus.HELD), distinct=True),
            due_this_week=Count(
                "id",
                filter=Q(deadline__range=(today, due_end))
                & ~Q(status__in=[PrdStatus.COMPLETED, PrdStatus.DROPPED]),
                distinct=True,
            ),
        )
        average = base.with_completion_rate().aggregate(value=Avg("completion_rate"))["value"]
        average_completion_rate = (
            int(Decimal(str(average)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if average is not None
            else 0
        )
        ai_coaching_count = AiUsageLog.objects.filter(
            prd_id__in=base.values("id"),
            feature_type=AiFeatureType.COACHING,
            action_type=AiActionType.CHAT,
            status=AiUsageStatus.SUCCESS,
        ).count()
        return {
            **counts,
            "average_completion_rate": average_completion_rate,
            "ai_coaching_count": ai_coaching_count,
        }

    @staticmethod
    def _apply_filters(
        queryset,
        *,
        filters: HomeFilters,
        context: IntegrationContext,
        tutor_mode: bool = False,
    ):
        if not tutor_mode and filters.scope == "mine":
            queryset = queryset.filter(
                Q(my_role__isnull=True) | ~Q(my_role=PrdParticipantRole.VIEWER)
            )
        elif not tutor_mode and filters.scope == "viewer":
            queryset = queryset.filter(my_role=PrdParticipantRole.VIEWER)

        if not tutor_mode and filters.tab == "project":
            queryset = queryset.filter(prd_type=PrdType.NEW_PRODUCT)
        elif not tutor_mode and filters.tab == "team":
            queryset = queryset.filter(Q(participant_count__gte=2) | Q(is_team_shared=True))
        elif not tutor_mode and filters.tab == "personal":
            queryset = queryset.filter(
                participant_count=1,
                is_team_shared=False,
                participants__user_id=context.user_id,
            )

        if filters.statuses and set(filters.statuses) != set(PrdStatus.values):
            queryset = queryset.filter(status__in=filters.statuses)
        if filters.prd_types:
            queryset = queryset.filter(prd_type__in=filters.prd_types)
        if filters.deadline_from:
            queryset = queryset.filter(deadline__gte=filters.deadline_from)
        if filters.deadline_to:
            queryset = queryset.filter(deadline__lte=filters.deadline_to)
        if filters.participant_user_id:
            if tutor_mode:
                selected_editor = PrdParticipant.objects.filter(
                    prd_id=OuterRef("pk"),
                    user_id=filters.participant_user_id,
                    role=PrdParticipantRole.EDITOR,
                )
                queryset = queryset.annotate(_has_selected_editor=Exists(selected_editor)).filter(
                    _has_selected_editor=True
                )
            else:
                queryset = queryset.filter(participants__user_id=filters.participant_user_id)
        if filters.team_id:
            queryset = queryset.filter(team_id=filters.team_id)
        queryset = HomeQueryService._apply_project_filters(queryset, filters=filters)
        return queryset

    @staticmethod
    def _apply_project_filters(queryset, *, filters: HomeFilters):
        if filters.round_scope == "none":
            queryset = queryset.filter(round_id__isnull=True)
        elif filters.round_scope != "all":
            queryset = queryset.filter(round_id=int(filters.round_scope))

        if filters.project_scope == "round_team":
            queryset = queryset.filter(round_id__isnull=False)
        elif filters.project_scope == "team":
            queryset = queryset.filter(round_id__isnull=True).filter(
                Q(participant_count__gte=2) | Q(is_team_shared=True)
            )
        elif filters.project_scope == "personal":
            queryset = queryset.filter(
                round_id__isnull=True,
                participant_count=1,
                is_team_shared=False,
            )
        return queryset

    @staticmethod
    def _apply_sort(queryset, sort):
        if sort == "deadline_asc":
            return queryset.order_by(F("deadline").asc(nulls_last=True), "-updated_at", "-id")
        if sort == "completion_desc":
            return queryset.order_by("-completion_rate", "-updated_at", "-id")
        if sort == "updated_desc":
            return queryset.order_by("-updated_at", "-id")
        if sort == "ai_coaching_desc":
            return queryset.order_by("-ai_coaching_count", "-updated_at", "-id")
        status_order = Case(
            When(status=PrdStatus.IN_PROGRESS, then=Value(0)),
            When(status=PrdStatus.COMPLETED, then=Value(1)),
            When(status=PrdStatus.HELD, then=Value(2)),
            When(status=PrdStatus.DROPPED, then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        )
        return queryset.order_by(status_order, "-updated_at", "-id")

    def _card_participants(self, *, prds):
        if not prds:
            return {}
        rows = list(
            PrdParticipant.objects.filter(prd_id__in=[prd.id for prd in prds])
            .annotate(
                card_rank=Window(
                    expression=RowNumber(),
                    partition_by=[F("prd_id")],
                    order_by=[F("created_at").asc(), F("id").asc()],
                )
            )
            .filter(card_rank__lte=4)
            .order_by("prd_id", "card_rank")
        )
        summaries = {}
        rows_by_round = {}
        prd_rounds = {prd.id: prd.round_id for prd in prds}
        roundless_rows = []
        for row in rows:
            round_id = prd_rounds[row.prd_id]
            if round_id is None:
                roundless_rows.append(row)
            else:
                rows_by_round.setdefault(round_id, []).append(row)
        if roundless_rows:
            summaries.update(
                {
                    (None, user_id): summary
                    for user_id, summary in self.repository.get_user_summaries(
                        user_ids=tuple(dict.fromkeys(row.user_id for row in roundless_rows)),
                    ).items()
                }
            )
        for round_id, round_rows in rows_by_round.items():
            summaries.update(
                {
                    (round_id, user_id): summary
                    for user_id, summary in self.repository.get_round_user_summaries(
                        user_ids=tuple(dict.fromkeys(row.user_id for row in round_rows)),
                        round_id=round_id,
                    ).items()
                }
            )
        result = {}
        for row in rows:
            summary = summaries.get((prd_rounds[row.prd_id], row.user_id))
            result.setdefault(row.prd_id, []).append(
                {
                    "user_id": row.user_id,
                    "participant_id": row.participant_id,
                    "display_name": (summary.display_name if summary else f"사용자 {row.user_id}"),
                    "role": row.role,
                }
            )
        return result

    @staticmethod
    def _serialize_card(*, prd, participants, today, context, tutor_mode=False):
        can_edit = bool(
            prd.my_role
            and role_permission_policy.allows(
                prd.my_role,
                ParticipantAction.EDIT,
                is_completed=prd.status == PrdStatus.COMPLETED,
            )
        )
        return {
            "id": prd.id,
            "version": prd.version,
            "title": prd.title,
            "description": prd.description,
            "prd_type": prd.prd_type,
            "status": prd.status,
            "show_new_badge": timezone.now() < prd.created_at + timedelta(hours=72),
            "completion_rate": prd.completion_rate,
            "deadline": prd.deadline.isoformat() if prd.deadline else None,
            "d_day": HomeQueryService._format_d_day(prd.deadline, today),
            "updated_at": prd.updated_at.isoformat(),
            "participants": participants,
            "participant_count": prd.participant_count,
            "my_role": prd.my_role,
            "can_edit": can_edit,
            "can_delete": bool(
                not tutor_mode
                and (prd.my_role == PrdParticipantRole.OWNER or is_admin_context(context))
            ),
            "ai_coaching_count": prd.ai_coaching_count,
            "round_id": prd.round_id,
            "team_id": prd.team_id,
            "project_scope": HomeQueryService._project_scope(prd),
        }

    @staticmethod
    def _project_scope(prd):
        if prd.round_id is not None:
            return "round_team"
        if prd.participant_count >= 2 or prd.is_team_shared:
            return "team"
        return "personal"

    @staticmethod
    def _format_d_day(deadline, today):
        if deadline is None:
            return None
        days = (deadline - today).days
        if days == 0:
            return "D-Day"
        return f"D-{days}" if days > 0 else f"D+{abs(days)}"

    @staticmethod
    def _serialize_filters(filters):
        return {
            "scope": filters.scope,
            "tab": filters.tab,
            "statuses": list(filters.statuses),
            "prd_types": list(filters.prd_types),
            "deadline_from": (filters.deadline_from.isoformat() if filters.deadline_from else None),
            "deadline_to": filters.deadline_to.isoformat() if filters.deadline_to else None,
            "participant_user_id": filters.participant_user_id,
            "team_id": filters.team_id,
            "round_scope": filters.round_scope,
            "project_scope": filters.project_scope,
            "dashboard_view": filters.dashboard_view,
            "sort": filters.sort,
        }
