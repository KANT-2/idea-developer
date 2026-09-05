from django.db import migrations

# 0010이 심은 프롬프트에 "거절한 제안을 다시 내지 말라"는 규칙을 더한 판이다.
# 이미 적용된 0010을 고치면 기존 설치본에 반영되지 않으므로 새 버전으로 올린다.

DECLINED_RULE = (
    "declined_proposals에 담긴 제안은 사용자가 이미 물린 것입니다. "
    "같은 질문에 같은 취지의 제안을 다시 내지 말고, 다른 방향을 제안하거나 제안을 생략하세요.\n"
)

ANCHOR = (
    "제안은 사용자가 화면에서 승인해야 반영되므로, "
    "승인 여부를 묻는 문장을 message에 덧붙이세요.\n"
)


def add_declined_rule(apps, schema_editor):
    AiPrompt = apps.get_model("ai", "AiPrompt")
    current = AiPrompt.objects.filter(feature_type="COACHING", is_active=True).first()
    if current is None or DECLINED_RULE in current.system_instructions:
        return
    if ANCHOR in current.system_instructions:
        instructions = current.system_instructions.replace(ANCHOR, ANCHOR + DECLINED_RULE, 1)
    else:
        instructions = current.system_instructions.rstrip() + "\n" + DECLINED_RULE

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


def remove_declined_rule(apps, schema_editor):
    AiPrompt = apps.get_model("ai", "AiPrompt")
    added = (
        AiPrompt.objects.filter(feature_type="COACHING", is_active=True)
        .order_by("-version")
        .first()
    )
    if added is None or DECLINED_RULE not in added.system_instructions:
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
    dependencies = [("ai", "0011_rename_chat_history_to_coach_chat_log")]

    operations = [
        migrations.RunPython(add_declined_rule, remove_declined_rule),
    ]
