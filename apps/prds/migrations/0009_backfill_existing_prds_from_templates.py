from django.db import migrations


LEGACY_SECTION_TARGETS = {
    "문제 정의": 5,
    "목표와 성공 지표": 7,
    "핵심 사용자 경험": 6,
}


def _rebuild_questions(question_model, section, template_questions):
    existing = list(question_model.objects.filter(section=section).order_by("position", "id"))
    template_prompts = [question.prompt for question in template_questions]
    matched_ids = set()

    for temporary_position, question in enumerate(existing, start=10001):
        question_model.objects.filter(pk=question.pk).update(position=temporary_position)

    for position, template_question in enumerate(template_questions, start=1):
        matched = next(
            (
                question
                for question in existing
                if question.pk not in matched_ids and question.prompt == template_question.prompt
            ),
            None,
        )
        if matched is None:
            question_model.objects.create(
                section=section,
                prompt=template_question.prompt,
                position=position,
            )
        else:
            matched_ids.add(matched.pk)
            question_model.objects.filter(pk=matched.pk).update(position=position)

    legacy_questions = [question for question in existing if question.pk not in matched_ids]
    for offset, question in enumerate(legacy_questions, start=1):
        question_model.objects.filter(pk=question.pk).update(
            position=len(template_questions) + offset
        )


def backfill_existing_prds(apps, schema_editor):
    prd_model = apps.get_model("prds", "Prd")
    template_model = apps.get_model("prds", "PrdTemplate")
    section_model = apps.get_model("prds", "PrdSection")
    question_model = apps.get_model("prds", "PrdQuestion")
    node_model = apps.get_model("brainstorm", "BrainstormNode")

    templates = {
        template.prd_type: template
        for template in template_model.objects.prefetch_related("sections__questions")
    }

    for prd in prd_model.objects.all().order_by("id"):
        template = templates.get(prd.prd_type)
        if template is None:
            continue
        template_sections = list(template.sections.all().order_by("position", "id"))
        existing_sections = list(
            section_model.objects.filter(prd=prd).order_by("position", "id")
        )
        selected = {}
        used_ids = set()

        for template_section in template_sections:
            exact = next(
                (
                    section
                    for section in existing_sections
                    if section.pk not in used_ids
                    and not section.is_deleted
                    and section.title == template_section.title
                ),
                None,
            )
            if exact is not None:
                selected[template_section.position] = exact
                used_ids.add(exact.pk)

        for section in existing_sections:
            target_position = LEGACY_SECTION_TARGETS.get(section.title)
            if (
                target_position is not None
                and target_position not in selected
                and section.pk not in used_ids
                and not section.is_deleted
            ):
                selected[target_position] = section
                used_ids.add(section.pk)

        for temporary_position, section in enumerate(existing_sections, start=1001):
            section_model.objects.filter(pk=section.pk).update(position=temporary_position)

        for template_section in template_sections:
            section = selected.get(template_section.position)
            if section is None:
                section = section_model.objects.create(
                    prd=prd,
                    title=template_section.title,
                    guide=template_section.guide,
                    position=template_section.position,
                )
            else:
                section_model.objects.filter(pk=section.pk).update(
                    title=template_section.title,
                    guide=template_section.guide,
                    position=template_section.position,
                )
            _rebuild_questions(
                question_model,
                section,
                list(template_section.questions.all().order_by("position", "id")),
            )

        extras = [section for section in existing_sections if section.pk not in used_ids]
        for offset, section in enumerate(extras, start=1):
            section_model.objects.filter(pk=section.pk).update(
                position=len(template_sections) + offset
            )

    node_model.objects.filter(node_type="note", section__isnull=False).exclude(
        status="held"
    ).update(status="accepted")
    node_model.objects.filter(node_type="note", section__isnull=True).exclude(
        status="held"
    ).update(status="default")


class Migration(migrations.Migration):
    dependencies = [
        ("prds", "0008_seed_confirmed_prd_templates"),
        ("brainstorm", "0004_normalize_note_status_by_section"),
    ]

    operations = [
        migrations.RunPython(backfill_existing_prds, migrations.RunPython.noop),
    ]
