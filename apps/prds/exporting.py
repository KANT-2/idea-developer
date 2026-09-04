from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Prefetch
from django.utils.text import slugify

from .models import Prd, PrdQuestion, PrdSection


@dataclass(frozen=True, slots=True)
class PrdMarkdownExport:
    content: bytes
    filename: str
    content_disposition: str


class PrdMarkdownExporter:
    def export(
        self,
        *,
        prd: Prd,
        exported_on: date | None = None,
    ) -> PrdMarkdownExport:
        exported_on = exported_on or date.today()
        sections = list(
            PrdSection.objects.filter(prd=prd, is_deleted=False)
            .prefetch_related(
                Prefetch(
                    "questions",
                    queryset=PrdQuestion.objects.filter(
                        is_deleted=False,
                        is_held=False,
                    )
                    .select_related("answer")
                    .order_by("position", "id"),
                ),
            )
            .order_by("position", "id")
        )
        markdown = self._render(prd=prd, sections=sections, exported_on=exported_on)
        filename = self._filename(prd=prd, exported_on=exported_on)
        encoded = quote(filename, safe="")
        return PrdMarkdownExport(
            content=markdown.encode("utf-8"),
            filename=filename,
            content_disposition=(
                f'attachment; filename="{filename}"; filename*=UTF-8\'\'{encoded}'
            ),
        )

    def _render(self, *, prd, sections, exported_on):
        lines = [
            f"# {self._heading(prd.title)}",
            "",
            f"> 작성일: {exported_on:%Y-%m-%d}  ",
            f"> 상태: {prd.get_status_display()}",
        ]
        if prd.deadline:
            lines.append(f"> 목표 마감일: {prd.deadline:%Y-%m-%d}")
        if prd.description.strip():
            lines.extend(["", prd.description.strip()])
        lines.extend(["", "---", ""])

        for index, section in enumerate(sections, 1):
            lines.extend([f"## {index}. {self._heading(section.title)}", ""])
            questions = list(section.questions.all())
            answered = [question for question in questions if self._answer(question)]
            if not answered:
                lines.extend(["> ⚠ 미작성", ""])
            else:
                for question in answered:
                    lines.extend(
                        [
                            f"**{question.prompt.strip()}**",
                            "",
                            self._answer(question),
                            "",
                        ]
                    )
            if index < len(sections):
                lines.extend(["---", ""])
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _answer(question: PrdQuestion):
        try:
            return question.answer.content.strip()
        except ObjectDoesNotExist:
            return ""

    @staticmethod
    def _heading(value):
        return " ".join(str(value).replace("#", "\\#").splitlines()).strip()

    @staticmethod
    def _filename(*, prd, exported_on):
        title = slugify(prd.title, allow_unicode=False)[:60].strip("-_") or "prd"
        return f"prd-{prd.pk}-{title}-{exported_on:%Y%m%d}.md"
