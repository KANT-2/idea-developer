from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.ai.models import AiActionType, AiFeatureType, AiJob, AiJobStatus
from apps.brainstorm.models import BrainstormConnection, BrainstormNode


@dataclass(frozen=True, slots=True)
class CleanupResult:
    nodes: int = 0
    connections: int = 0
    ai_previews: int = 0


class BackgroundDataCleanupService:
    """Purge recoverable data only after its configured retention window."""

    def run(self, *, now=None, dry_run=False) -> CleanupResult:
        now = now or timezone.now()
        nodes, connections = self.purge_deleted_brainstorm_data(
            cutoff=now - timedelta(days=settings.BRAINSTORM_DELETE_RETENTION_DAYS),
            dry_run=dry_run,
        )
        previews = self.clear_expired_ai_previews(
            cutoff=now - timedelta(days=settings.AI_PREVIEW_RETENTION_DAYS),
            dry_run=dry_run,
        )
        return CleanupResult(nodes=nodes, connections=connections, ai_previews=previews)

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
    def clear_expired_ai_previews(*, cutoff, dry_run=False):
        preview_filter = (
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
                finished_at__lte=cutoff,
                output_data__isnull=False,
            )
            .order_by("finished_at", "id")
            .values_list("pk", flat=True)[: settings.BACKGROUND_CLEANUP_BATCH_SIZE]
        )
        if dry_run:
            return len(ids)
        return AiJob.objects.filter(pk__in=ids).update(output_data=None)
