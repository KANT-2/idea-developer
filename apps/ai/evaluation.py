from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.prds.models import Prd, PrdQuestion

from .coaching import PrdAiContextBuilder, sanitize_ai_markdown
from .exceptions import AiOutputValidationError
from .models import AiActionType, AiFeatureType, AiJob, AiJobStatus
from .services import AiJobService

EVALUATION_PERSONAS = {
    "pm": {
        "label": "PM 관점",
        "focus": (
            "비즈니스 타당성, 이 기능이 지금 필요한 이유, 성공 지표가 실제로 무엇을 "
            "측정하는지, 우선순위 판단의 근거, 사용자와 팀에 미치는 영향을 중심으로 "
            "본다. 구현 방법이나 기술적 세부사항은 낮은 비중으로 다룬다."
        ),
    },
    "engineering": {
        "label": "엔지니어링 관점",
        "focus": (
            "구현 가능성, 데이터 모델과 연동 관계의 누락, 예외 상황 처리, 확장성과 "
            "유지보수 비용을 중심으로 본다. 사업적 타당성이나 시장성은 낮은 비중으로 "
            "다룬다."
        ),
    },
    "investor": {
        "label": "투자자 관점",
        "focus": (
            "이 제품/기능이 왜 지금 우선순위인지, 경쟁 대안 대비 차별성이 설득력 "
            "있는지, 핵심 가설이 검증 가능한 방식으로 설계되어 있는지를 중심으로 "
            "본다. 세부 UX나 데이터 모델 이슈는 낮은 비중으로 다룬다."
        ),
    },
}


class PrdEvaluationService:
    def request(
        self,
        *,
        prd: Prd,
        user_id: int,
        persona: Any,
        idempotency_key: str,
    ) -> tuple[AiJob, bool]:
        if persona not in EVALUATION_PERSONAS:
            raise ValidationError({"persona": "지원하는 진단 관점을 선택해 주세요."})
        context = PrdAiContextBuilder().build(prd=prd, section=None)
        if not context["sections"]:
            raise ValidationError({"prd": "진단할 PRD 섹션이 없습니다."})
        versions = {
            str(question["id"]): question["version"]
            for section in context["sections"]
            for question in section["questions"]
        }
        return AiJobService().enqueue(
            prd=prd,
            user_id=user_id,
            feature_type=AiFeatureType.PRD_EVALUATION,
            action_type=AiActionType.EVALUATION,
            input_data={
                "kind": "prd_evaluation",
                "persona": persona,
                "persona_label": EVALUATION_PERSONAS[persona]["label"],
                "evaluation_focus": EVALUATION_PERSONAS[persona]["focus"],
                "question_versions": versions,
                "context": context,
            },
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def latest(
        *,
        prd: Prd,
        user_id: int,
        jobs_by_persona: dict[str, AiJob] | None = None,
    ) -> AiJob | None:
        jobs = (
            jobs_by_persona
            if jobs_by_persona is not None
            else PrdEvaluationService.latest_by_persona(prd=prd, user_id=user_id)
        ).values()
        active_statuses = {
            AiJobStatus.QUEUED,
            AiJobStatus.RUNNING,
            AiJobStatus.RETRY_WAIT,
            AiJobStatus.CANCEL_REQUESTED,
        }
        active = [job for job in jobs if job.status in active_statuses]
        if active:
            return max(active, key=lambda job: (job.created_at, str(job.pk)))
        succeeded = [job for job in jobs if job.status == AiJobStatus.SUCCEEDED]
        return (
            max(succeeded, key=lambda job: (job.finished_at or job.created_at, str(job.pk)))
            if succeeded
            else None
        )

    @staticmethod
    def latest_by_persona(*, prd: Prd, user_id: int) -> dict[str, AiJob]:
        """Return one restorable or active diagnosis for every supported perspective."""
        active_statuses = [
            AiJobStatus.QUEUED,
            AiJobStatus.RUNNING,
            AiJobStatus.RETRY_WAIT,
            AiJobStatus.CANCEL_REQUESTED,
        ]
        candidates = (
            AiJob.objects.filter(
                prd=prd,
                feature_type=AiFeatureType.PRD_EVALUATION,
                action_type=AiActionType.EVALUATION,
            )
            .filter(
                Q(user_id=user_id, status__in=active_statuses)
                | Q(status=AiJobStatus.SUCCEEDED)
            )
            .select_related("prompt")
            .order_by("-created_at", "-id")
        )
        selected: dict[str, AiJob] = {}
        for job in candidates:
            persona = job.input_data.get("persona")
            if persona not in EVALUATION_PERSONAS:
                continue
            current = selected.get(persona)
            if current is None:
                selected[persona] = job
                continue
            job_is_active = job.user_id == user_id and job.status in active_statuses
            current_is_active = current.user_id == user_id and current.status in active_statuses
            if job_is_active and not current_is_active:
                selected[persona] = job
        return selected

    @staticmethod
    def is_current(job: AiJob) -> bool:
        snapshot = job.input_data.get("question_versions") or {}
        current = {
            str(question_id): version
            for question_id, version in PrdQuestion.objects.filter(
                section__prd=job.prd,
                section__is_deleted=False,
                is_deleted=False,
                is_held=False,
            ).values_list("id", "version")
        }
        return snapshot == current


class PrdEvaluationResultProcessor:
    def process(self, *, job: AiJob, output: dict[str, Any]) -> dict[str, Any]:
        if (
            job.feature_type != AiFeatureType.PRD_EVALUATION
            or job.action_type != AiActionType.EVALUATION
        ):
            return output
        expected_section_ids = {
            section["id"] for section in job.input_data["context"]["sections"]
        }
        section_rows = output.get("sections")
        if not isinstance(section_rows, list):
            raise AiOutputValidationError("PRD evaluation sections must be an array.")
        returned_ids = [row.get("section_id") for row in section_rows]
        if len(returned_ids) != len(set(returned_ids)):
            raise AiOutputValidationError("PRD evaluation repeated a section identifier.")
        if set(returned_ids) != expected_section_ids:
            raise AiOutputValidationError("PRD evaluation must cover every current section once.")
        return {
            "persona": job.input_data["persona"],
            "persona_label": job.input_data["persona_label"],
            "overall_score": output["overall_score"],
            "summary": sanitize_ai_markdown(output["summary"]),
            "strengths": [sanitize_ai_markdown(value) for value in output["strengths"]],
            "improvements": [
                sanitize_ai_markdown(value) for value in output["improvements"]
            ],
            "sections": [
                {
                    "section_id": row["section_id"],
                    "score": row["score"],
                    "status": row["status"],
                    "feedback": sanitize_ai_markdown(row["feedback"]),
                    "missing_points": [
                        sanitize_ai_markdown(value) for value in row["missing_points"]
                    ],
                }
                for row in section_rows
            ],
        }
