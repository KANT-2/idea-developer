from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.ai.models import (
    AiActionType,
    AiFeatureType,
    AiJob,
    AiJobStatus,
    AiPrdApplyRecord,
    ContributionEvaluation,
)
from apps.brainstorm.models import BrainstormConnection, BrainstormNode
from apps.prds.models import Prd, PrdDeletionAction, PrdDeletionAuditLog


@dataclass(frozen=True, slots=True)
class CleanupResult:
    prds: int = 0
    nodes: int = 0
    connections: int = 0
    ai_previews: int = 0


class BackgroundDataCleanupService:
    """Purge recoverable data only after its configured retention window."""

    def run(self, *, now=None, dry_run=False) -> CleanupResult:
        now = now or timezone.now()
        prds = self.purge_deleted_prds(
            cutoff=now - timedelta(days=settings.PRD_TRASH_RETENTION_DAYS),
            dry_run=dry_run,
        )
        nodes, connections = self.purge_deleted_brainstorm_data(
            cutoff=now - timedelta(days=settings.BRAINSTORM_DELETE_RETENTION_DAYS),
            dry_run=dry_run,
        )
        previews = self.clear_expired_ai_previews(
            cutoff=now - timedelta(days=settings.AI_PREVIEW_RETENTION_DAYS),
            chat_cutoff=now - timedelta(days=settings.AI_CHAT_PAYLOAD_RETENTION_DAYS),
            dry_run=dry_run,
        )
        return CleanupResult(
            prds=prds,
            nodes=nodes,
            connections=connections,
            ai_previews=previews,
        )

    @staticmethod
    @transaction.atomic
    def purge_deleted_prds(*, cutoff, dry_run=False):
        prds = list(
            Prd.objects.select_for_update(skip_locked=True)
            .filter(is_deleted=True, deleted_at__lte=cutoff)
            .order_by("deleted_at", "id")[: settings.BACKGROUND_CLEANUP_BATCH_SIZE]
        )
        if dry_run:
            return len(prds)
        for prd in prds:
            PrdDeletionAuditLog.objects.create(
                prd_id=prd.pk,
                title_snapshot=prd.title,
                creator_user_id=prd.creator_user_id,
                actor_user_id=None,
                action=PrdDeletionAction.PURGED,
                details={"deleted_at": prd.deleted_at.isoformat()},
            )
        if prds:
            prd_ids = [prd.pk for prd in prds]
            # These records intentionally protect the exact source rows used for
            # AI application and contribution calculation while a PRD exists.
            # At the end of the PRD retention window the detailed records share
            # the PRD's lifecycle, so remove their roots before the PRD cascade.
            AiPrdApplyRecord.objects.filter(prd_id__in=prd_ids).delete()
            ContributionEvaluation.objects.filter(prd_id__in=prd_ids).delete()
            Prd.objects.filter(pk__in=prd_ids).delete()
        return len(prds)

    @staticmethod
    @transaction.atomic
    def purge_deleted_brainstorm_data(*, cutoff, dry_run=False):
        node_ids = list(
            BrainstormNode.objects.filter(is_deleted=True, deleted_at__lte=cutoff)
            .order_by("deleted_at", "id")
            .values_list("pk", flat=True)[: settings.BACKGROUND_CLEANUP_BATCH_SIZE]
        )
        connection_filter = Q(is_deleted=True, deleted_at__lte=cutoff)
        if node_ids:
            connection_filter |= Q(node_a_id__in=node_ids) | Q(node_b_id__in=node_ids)
        connection_ids = list(
            BrainstormConnection.objects.filter(connection_filter)
            .order_by("deleted_at", "id")
            .values_list("pk", flat=True)[: settings.BACKGROUND_CLEANUP_BATCH_SIZE]
        )
        if dry_run:
            return len(node_ids), len(connection_ids)
        deleted_connections = 0
        if connection_ids:
            deleted_connections, _ = BrainstormConnection.objects.filter(
                pk__in=connection_ids
            ).delete()
        deleted_nodes = 0
        if node_ids:
            deleted_nodes, details = BrainstormNode.objects.filter(pk__in=node_ids).delete()
            deleted_connections += details.get(BrainstormConnection._meta.label, 0)
        return deleted_nodes, deleted_connections

    @staticmethod
    @transaction.atomic
    def clear_expired_ai_previews(*, cutoff, chat_cutoff=None, dry_run=False):
        """미리보기 성격의 결과를 비운다.

        채팅 결과에는 코치의 수정 제안 전문이 들어 있어 대화와 같은 기간 동안 남긴다.
        나머지 미리보기는 기존 보관 기간을 그대로 쓴다.
        """
        chat_cutoff = cutoff if chat_cutoff is None else chat_cutoff
        preview_filter = Q(
            Q(
                Q(
                    feature_type=AiFeatureType.BRAINSTORM_ANALYSIS,
                    action_type=AiActionType.ANALYSIS,
                )
                | Q(
                    feature_type=AiFeatureType.BRAINSTORM_CLASSIFICATION,
                    action_type=AiActionType.CLASSIFICATION,
                )
                | Q(
                    feature_type=AiFeatureType.BRAINSTORM_PRD_APPLY,
                    action_type=AiActionType.PRD_APPLY,
                )
                | Q(feature_type=AiFeatureType.COACHING, action_type=AiActionType.DRAFT)
            ),
            finished_at__lte=cutoff,
        ) | Q(
            feature_type=AiFeatureType.COACHING,
            action_type=AiActionType.CHAT,
            finished_at__lte=chat_cutoff,
        )
        ids = list(
            AiJob.objects.filter(
                preview_filter,
                status__in=[
                    AiJobStatus.SUCCEEDED,
                    AiJobStatus.FAILED,
                    AiJobStatus.CANCELLED,
                    AiJobStatus.TIMED_OUT,
                ],
                output_data__isnull=False,
            )
            .order_by("finished_at", "id")
            .values_list("pk", flat=True)[: settings.BACKGROUND_CLEANUP_BATCH_SIZE]
        )
        if dry_run:
            return len(ids)
        return AiJob.objects.filter(pk__in=ids).update(output_data=None)
