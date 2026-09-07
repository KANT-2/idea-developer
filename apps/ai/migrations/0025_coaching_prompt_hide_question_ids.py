from django.db import migrations

# 사용자가 실제로 겪는 문제를 신고: "AI 코치가 message에서 질문을 (id: 260)처럼
# 내부 DB id로 언급한다"는 스크린샷. proposal.question_id는 구조화된 필드라
# 내부 id를 써야 하지만, message는 사람이 읽는 화면 텍스트라 내부 id가 그대로
# 노출되면 안 된다 — 기존 프롬프트는 이 둘을 구분해서 지시하지 않았다.

ANCHOR = "kind가 coach_chat이면 message에 사용자에게 보여줄 답변을 담습니다. "

HIDE_ID_RULE = (
    "message 안에서 특정 질문을 가리킬 때는 내부 id 숫자를 그대로 쓰지 말고 "
    "그 질문의 실제 문구(prompt)로 지칭하세요 — 예를 들어 \"(id: 260)\" 대신 "
    "\"'프로젝트를 한 줄로 소개하면 무엇인가요?' 질문\"처럼 쓰세요. id는 "
    "proposal.question_id 필드에만 쓰고 message 텍스트에는 절대 노출하지 마세요. "
)


def add_hide_id_rule(apps, schema_editor):
    AiPrompt = apps.get_model("ai", "AiPrompt")
    current = AiPrompt.objects.filter(feature_type="COACHING", is_active=True).first()
    if current is None or HIDE_ID_RULE in current.system_instructions:
        return
    if ANCHOR in current.system_instructions:
        instructions = current.system_instructions.replace(
            ANCHOR, ANCHOR + HIDE_ID_RULE, 1
        )
    else:
        instructions = current.system_instructions.rstrip() + "\n" + HIDE_ID_RULE

    latest_version = (
        AiPrompt.objects.filter(feature_type="COACHING")
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
        or 0
    )
    AiPrompt.objects.filter(feature_type="COACHING", is_active=True).update(is_active=False)
    AiPrompt.objects.create(
        feature_type="COACHING",
        version=latest_version + 1,
        system_instructions=instructions,
        output_schema=current.output_schema,
        model=current.model,
        is_active=True,
    )


def remove_hide_id_rule(apps, schema_editor):
    AiPrompt = apps.get_model("ai", "AiPrompt")
    added = (
        AiPrompt.objects.filter(feature_type="COACHING", is_active=True)
        .order_by("-version")
        .first()
    )
    if added is None or HIDE_ID_RULE not in added.system_instructions:
        return
    previous = (
        AiPrompt.objects.filter(feature_type="COACHING", version__lt=added.version)
        .order_by("-version")
        .first()
    )
    added.delete()
    if previous is not None:
        previous.is_active = True
        previous.save(update_fields=["is_active", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("ai", "0024_perspective_draft_prompt_v3")]

    operations = [
        migrations.RunPython(add_hide_id_rule, remove_hide_id_rule),
    ]
