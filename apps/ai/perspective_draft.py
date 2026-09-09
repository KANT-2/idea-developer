from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.prds.models import Prd, PrdAnswer

from .coaching import PrdAiContextBuilder, _apply_answer, sanitize_ai_markdown
from .evaluation import EVALUATION_PERSONAS, PrdEvaluationService
from .exceptions import AiOutputValidationError
from .models import AiActionType, AiFeatureType, AiJob, AiJobStatus
from .services import AiJobService


class PrdPerspectiveDraftService:
    def request(
        self,
        *,
        prd: Prd,
        user_id: int,
        idempotency_key: str,
    ) -> tuple[AiJob, bool]:
        context = PrdAiContextBuilder().build(prd=prd, section=None)
        if not context["sections"]:
            raise ValidationError({"prd": "초안을 작성할 PRD 섹션이 없습니다."})
        versions = {
            str(question["id"]): question["version"]
            for section in context["sections"]
            for question in section["questions"]
        }
        if not versions:
            raise ValidationError({"prd": "초안을 작성할 활성 질문이 없습니다."})
        input_data = {
            "kind": "prd_perspective_draft",
            "personas": [
                {"key": key, "label": value["label"], "focus": value["focus"]}
                for key, value in EVALUATION_PERSONAS.items()
            ],
            "question_versions": versions,
            "context": context,
        }
        references = self._reference_diagnoses(prd=prd, user_id=user_id)
        if references:
            input_data["reference_diagnoses"] = references
        return AiJobService().enqueue(
            prd=prd,
            user_id=user_id,
            feature_type=AiFeatureType.PRD_PERSPECTIVE_DRAFT,
            action_type=AiActionType.PERSPECTIVE_DRAFT,
            input_data=input_data,
            idempotency_key=idempotency_key,
            # PRD 전체(질문 수십 개)를 한 번에 쓰기 때문에 기본 타임아웃
            # (AI_JOB_TIMEOUT_SECONDS, 30초)로는 부족하다. gemini-3.5-flash-lite로
            # 여러 질문의 초안을 한 번에 만들 때 15~25초가 걸리는 것을 확인해 여유를 두고
            # 60초로 잡았다.
            timeout_seconds=60,
        )

    @staticmethod
    def _reference_diagnoses(*, prd, user_id):
        """세 관점의 최신 AI 진단 결과를 참고 자료로만 곁들인다.

        관점별로 없거나, 실패했거나, 지금 PRD 내용과 안 맞으면(버전이 다르면) 그
        관점만 빼고, 하나도 없으면 아예 생략한다 — 초안 작성은 진단 없이도 PRD
        내용만으로 동작해야 한다.
        """
        jobs_by_persona = PrdEvaluationService.latest_by_persona(prd=prd, user_id=user_id)
        references = []
        for persona, job in jobs_by_persona.items():
            if job is None or job.status != AiJobStatus.SUCCEEDED or not job.output_data:
                continue
            if not PrdEvaluationService.is_current(job):
                continue
            output = job.output_data
            references.append(
                {
                    "persona": persona,
                    "persona_label": EVALUATION_PERSONAS[persona]["label"],
                    "overall_score": output.get("overall_score"),
                    "summary": output.get("summary"),
                    "improvements": output.get("improvements", []),
                    "sections": [
                        {
                            "section_id": row["section_id"],
                            "status": row["status"],
                            "missing_points": row.get("missing_points", []),
                        }
                        for row in output.get("sections", [])
                    ],
                }
            )
        return references

    @transaction.atomic
    def apply(
        self,
        *,
        job: AiJob,
        approved_questions: Any,
        user_id: int,
    ) -> list[PrdAnswer]:
        job = AiJob.objects.select_for_update().select_related("prd").get(pk=job.pk)
        if (
            job.user_id != user_id
            or job.feature_type != AiFeatureType.PRD_PERSPECTIVE_DRAFT
            or job.action_type != AiActionType.PERSPECTIVE_DRAFT
            or job.status != AiJobStatus.SUCCEEDED
        ):
            raise ValidationError({"job": "반영할 수 있는 PRD 초안 작업이 아닙니다."})
        approvals = self._approvals(approved_questions)
        answers_by_question = {
            row["question_id"]: row for row in (job.output_data or {}).get("answers", [])
        }
        if not set(approvals).issubset(answers_by_question):
            raise ValidationError({"approved_questions": "미리보기 결과와 일치하지 않습니다."})
        applied = []
        for question_id, version in approvals.items():
            row = answers_by_question[question_id]
            answer = _apply_answer(
                prd=job.prd,
                question_id=question_id,
                generated_version=job.input_data["question_versions"][str(question_id)],
                question_version=version,
                content=row["draft"],
                user_id=user_id,
                event_type="ai_perspective_draft_applied",
                job=job,
            )
            applied.append(answer)
        return applied

    @staticmethod
    def _approvals(value):
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(row, dict) for row in value)
        ):
            raise ValidationError({"approved_questions": "승인할 질문이 하나 이상 필요합니다."})
        result = {}
        for row in value:
            question_id = row.get("question_id")
            version = row.get("version")
            if (
                isinstance(question_id, bool)
                or not isinstance(question_id, int)
                or question_id < 1
                or isinstance(version, bool)
                or not isinstance(version, int)
                or version < 1
            ):
                raise ValidationError(
                    {"approved_questions": "질문 ID와 version이 올바르지 않습니다."}
                )
            if question_id in result:
                raise ValidationError({"approved_questions": "질문을 중복 승인할 수 없습니다."})
            result[question_id] = version
        return result


class PrdPerspectiveDraftResultProcessor:
    def process(self, *, job: AiJob, output: dict[str, Any]) -> dict[str, Any]:
        if (
            job.feature_type != AiFeatureType.PRD_PERSPECTIVE_DRAFT
            or job.action_type != AiActionType.PERSPECTIVE_DRAFT
        ):
            return output
        expected_ids = {int(key) for key in job.input_data.get("question_versions", {})}
        rows = output.get("answers")
        if not isinstance(rows, list):
            raise AiOutputValidationError("Perspective draft answers must be an array.")
        answers = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise AiOutputValidationError("Each perspective draft answer must be an object.")
            question_id = row.get("question_id")
            if isinstance(question_id, bool) or not isinstance(question_id, int):
                raise AiOutputValidationError("question_id must be an integer.")
            if question_id in seen or question_id not in expected_ids:
                raise AiOutputValidationError(
                    "Perspective draft referenced an unavailable or duplicate question."
                )
            seen.add(question_id)
            draft = sanitize_ai_markdown(row.get("draft")).strip()
            if not draft:
                raise AiOutputValidationError("Perspective draft returned an empty answer.")
            answers.append(
                {
                    "question_id": question_id,
                    "question_version": job.input_data["question_versions"][str(question_id)],
                    "draft": draft,
                    "reasoning": sanitize_ai_markdown(row.get("reasoning")),
                }
            )
        if seen != expected_ids:
            raise AiOutputValidationError(
                "Perspective draft must cover every current question once."
            )
        return {"answers": answers}
