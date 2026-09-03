from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.text import slugify

from .models import (
    BrainstormCanvas,
    BrainstormConnection,
    BrainstormNode,
    BrainstormNodeStatus,
    BrainstormNodeType,
)


@dataclass(frozen=True, slots=True)
class MarkdownExportOptions:
    scope: str = "all"
    organization: str = "section"
    include_unclassified: bool = True

    @classmethod
    def from_query(cls, query):
        scope = query.get("scope", "all")
        organization = query.get("organization", "section")
        raw_unclassified = query.get("include_unclassified", "true").lower()
        errors = {}
        if scope not in {"all", "accepted"}:
            errors["scope"] = "scope은 all 또는 accepted여야 합니다."
        if organization not in {"section", "flat"}:
            errors["organization"] = "organization은 section 또는 flat이어야 합니다."
        if raw_unclassified not in {"true", "false"}:
            errors["include_unclassified"] = "true 또는 false를 사용해 주세요."
        if errors:
            raise ValidationError(errors)
        return cls(
            scope=scope,
            organization=organization,
            include_unclassified=raw_unclassified == "true",
        )


@dataclass(frozen=True, slots=True)
class MarkdownExport:
    content: bytes
    filename: str
    content_disposition: str


class BrainstormMarkdownExporter:
    def export(
        self,
        *,
        canvas: BrainstormCanvas,
        options: MarkdownExportOptions,
        exported_on: date | None = None,
    ) -> MarkdownExport:
        exported_on = exported_on or date.today()
        nodes = self._nodes(canvas=canvas, options=options)
        labels = {node.pk: f"IDEA-{index:03d}" for index, node in enumerate(nodes, 1)}
        connections = self._connections(canvas=canvas, node_ids=set(labels))
        markdown = self._render(
            canvas=canvas,
            nodes=nodes,
            labels=labels,
            connections=connections,
            options=options,
        )
        filename = self._filename(canvas=canvas, exported_on=exported_on)
        encoded = quote(filename, safe="")
        return MarkdownExport(
            content=markdown.encode("utf-8"),
            filename=filename,
            content_disposition=f'attachment; filename="{filename}"; filename*=UTF-8\'\'{encoded}',
        )

    @staticmethod
    def _nodes(*, canvas, options):
        queryset = (
            BrainstormNode.objects.filter(
                canvas=canvas,
                node_type=BrainstormNodeType.NOTE,
                is_deleted=False,
            )
            .exclude(status=BrainstormNodeStatus.HELD)
            .select_related("section")
        )
        if options.scope == "accepted":
            queryset = queryset.filter(status=BrainstormNodeStatus.ACCEPTED)
        if not options.include_unclassified:
            queryset = queryset.filter(section__isnull=False)
        return list(queryset.order_by("section__position", "section_id", "created_at", "id"))

    @staticmethod
    def _connections(*, canvas, node_ids):
        related = defaultdict(list)
        if not node_ids:
            return related
        rows = BrainstormConnection.objects.filter(
            canvas=canvas,
            is_deleted=False,
            node_a_id__in=node_ids,
            node_b_id__in=node_ids,
        ).filter(Q(node_a__is_deleted=False) & Q(node_b__is_deleted=False))
        for row in rows:
            related[row.node_a_id].append(row.node_b_id)
            related[row.node_b_id].append(row.node_a_id)
        return related

    def _render(self, *, canvas, nodes, labels, connections, options):
        scope_label = "채택 메모" if options.scope == "accepted" else "전체 활성 메모"
        lines = [
            f"# {self._heading(canvas.prd.title)} 브레인스토밍",
            "",
            f"- 내보내기 범위: {scope_label}",
            f"- 미분류 포함: {'예' if options.include_unclassified else '아니요'}",
            f"- 메모 수: {len(nodes)}",
            "",
        ]
        if not nodes:
            lines.extend(["내보낼 메모가 없습니다.", ""])
            return "\n".join(lines)

        if options.organization == "flat":
            lines.extend(["## 아이디어 목록", ""])
            for node in nodes:
                self._append_node(lines, node=node, labels=labels, connections=connections)
            return "\n".join(lines)

        grouped = defaultdict(list)
        for node in nodes:
            grouped[node.section_id].append(node)
        section_order = []
        seen = set()
        for node in nodes:
            if node.section_id is not None and node.section_id not in seen:
                section_order.append((node.section_id, node.section.title))
                seen.add(node.section_id)
        for section_id, title in section_order:
            lines.extend([f"## {self._heading(title)}", ""])
            for node in grouped[section_id]:
                self._append_node(lines, node=node, labels=labels, connections=connections)
        if grouped.get(None):
            lines.extend(["## 미분류", ""])
            for node in grouped[None]:
                self._append_node(lines, node=node, labels=labels, connections=connections)
        return "\n".join(lines)

    @staticmethod
    def _append_node(lines, *, node, labels, connections):
        lines.extend([f"### {labels[node.pk]}", "", node.content.strip(), ""])
        connected = sorted(connections[node.pk], key=lambda node_id: labels[node_id])
        if connected:
            lines.append("연결된 아이디어:")
            lines.extend(f"- {labels[node_id]}" for node_id in connected)
        else:
            lines.append("연결된 아이디어: 없음")
        lines.append("")

    @staticmethod
    def _heading(value):
        return " ".join(str(value).replace("#", "\\#").splitlines()).strip()

    @staticmethod
    def _filename(*, canvas, exported_on):
        title = slugify(canvas.prd.title, allow_unicode=False)[:60].strip("-_")
        title = title or "prd"
        return f"brainstorm-{canvas.prd_id}-{title}-{exported_on:%Y%m%d}.md"
