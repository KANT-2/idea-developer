from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import ceil

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Avg, Case, Count, F, IntegerField, Q, Value, When, Window
from django.db.models.functions import RowNumber, TruncDate
from django.utils import timezone

from apps.accounts.permissions import ParticipantAction, role_permission_policy
from apps.ai.models import AiActionType, AiFeatureType, AiUsageLog, AiUsageStatus
from apps.integration.context import IntegrationContext
from apps.integration.repository import IntegrationRepository

from .models import (
    Prd,
    PrdChangeHistory,
    PrdParticipant,
    PrdParticipantRole,
    PrdStatus,
    PrdType,
)

HOME_TABS = {"all", "project", "team", "personal"}
HOME_SCOPES = {"all", "mine", "viewer"}
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
        if errors:
            raise ValidationError(errors)


class HomeQueryService:
    def __init__(self, repository: IntegrationRepository):
        self.repository = repository

    def get_home(self, *, context: IntegrationContext, filters: HomeFilters):
        filters.validate(context=context)
        today = timezone.localdate()
        base = Prd.objects.accessible_home(
            user_id=context.user_id,
            round_id=context.round_id,
            team_id=context.team_id,
        )
        kpis = self._get_kpis(base=base, today=today)
        queryset = self._apply_filters(
            base.with_home_metrics(user_id=context.user_id),
            filters=filters,
            context=context,
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
            "items": [
                self._serialize_card(
                    prd=prd,
                    participants=participants_by_prd.get(prd.id, []),
                    today=today,
                    context=context,
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
        base = Prd.objects.accessible_home(
            user_id=context.user_id,
            round_id=context.round_id,
            team_id=context.team_id,
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
    def _apply_filters(queryset, *, filters: HomeFilters, context: IntegrationContext):
        if filters.scope == "mine":
            queryset = queryset.filter(
                Q(my_role__isnull=True) | ~Q(my_role=PrdParticipantRole.VIEWER)
            )
        elif filters.scope == "viewer":
            queryset = queryset.filter(my_role=PrdParticipantRole.VIEWER)

        if filters.tab == "project":
            queryset = queryset.filter(prd_type=PrdType.NEW_PRODUCT)
        elif filters.tab == "team":
            queryset = queryset.filter(Q(participant_count__gte=2) | Q(is_team_shared=True))
        elif filters.tab == "personal":
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
            queryset = queryset.filter(participants__user_id=filters.participant_user_id)
        if filters.team_id:
            queryset = queryset.filter(team_id=filters.team_id)
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
    def _serialize_card(*, prd, participants, today, context):
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
                prd.my_role == PrdParticipantRole.OWNER
                or context.is_staff
                or context.is_superuser
            ),
            "ai_coaching_count": prd.ai_coaching_count,
        }

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
            "sort": filters.sort,
        }
