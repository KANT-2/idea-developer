from django.db import migrations

# v3의 "반드시 두 문단, 250자 이상"이 모든 질문에 획일적으로 적용돼서,
# 프로젝트명처럼 원래 한 문장이면 충분한 질문까지 억지로 늘어난다는 사용자
# 피드백을 받았다. 질문 성격(간결해야 하는 것 vs 설명이 필요한 것)에 따라
# 분량을 다르게 판단하도록 지침을 바꿨다.
#
# 검증: 실제 호출로 확인 — "프로젝트명은 무엇인가요?"는 37자 한 문장으로
# 짧게 유지되고("기존 답변이 명확하게 잘 전달하고 있어 그대로 유지"), 배경·
# 목표처럼 설명이 필요한 질문은 100~190자로 필요한 만큼 풀어 썼다. 등장하는
# 수치는 전부 기존 저장된 답변에서 인용한 것뿐이었다.

PRD_PERSPECTIVE_DRAFT_LENGTH_RULE_V3 = (
    "draft는 반드시 두 문단으로 나눠 쓰고, 전체 250자 이상이 되도록 충분히 "
    "풀어서 설명하세요. 첫 문단에서는 핵심 내용을, 두 번째 문단에서는 왜 "
    "중요한지와 관련 관점의 고려사항을 설명하세요. 한두 문장으로 짧게 끝내지 "
    "마세요."
)

PRD_PERSPECTIVE_DRAFT_LENGTH_RULE_V4 = (
    "질문의 성격에 따라 분량을 다르게 판단하세요. 프로젝트명, 한 줄 소개, "
    "날짜처럼 원래 짧고 명확한 게 정답인 질문은 억지로 늘리지 말고 간결하게 "
    "답하세요. 배경, 문제 정의, 목표, 범위처럼 설명과 근거가 필요한 질문은 "
    "두 문단으로 나눠 전체 250자 이상 충분히 풀어서 설명하세요 — 첫 문단에서는 "
    "핵심 내용을, 두 번째 문단에서는 왜 중요한지와 관련 관점의 고려사항을 "
    "설명하세요. 짧게 답해도 되는 질문을 억지로 늘리거나, 설명이 필요한 "
    "질문을 한두 문장으로 짧게 끝내지 마세요."
)


def add_v4(apps, schema_editor):
    AiPrompt = apps.get_model("ai", "AiPrompt")
    current = AiPrompt.objects.filter(feature_type="PRD_PERSPECTIVE_DRAFT", is_active=True).first()
    if current is None or PRD_PERSPECTIVE_DRAFT_LENGTH_RULE_V3 not in current.system_instructions:
        return
    instructions = current.system_instructions.replace(
        PRD_PERSPECTIVE_DRAFT_LENGTH_RULE_V3, PRD_PERSPECTIVE_DRAFT_LENGTH_RULE_V4, 1
    )
    latest_version = (
        AiPrompt.objects.filter(feature_type="PRD_PERSPECTIVE_DRAFT")
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
        or 0
    )
    AiPrompt.objects.filter(feature_type="PRD_PERSPECTIVE_DRAFT", is_active=True).update(
        is_active=False
    )
    AiPrompt.objects.create(
        feature_type="PRD_PERSPECTIVE_DRAFT",
        version=latest_version + 1,
        system_instructions=instructions,
        output_schema=current.output_schema,
        model=current.model,
        is_active=True,
    )


def remove_v4(apps, schema_editor):
    AiPrompt = apps.get_model("ai", "AiPrompt")
    added = (
        AiPrompt.objects.filter(feature_type="PRD_PERSPECTIVE_DRAFT", is_active=True)
        .order_by("-version")
        .first()
    )
    if added is None or PRD_PERSPECTIVE_DRAFT_LENGTH_RULE_V4 not in added.system_instructions:
        return
    previous = (
        AiPrompt.objects.filter(
            feature_type="PRD_PERSPECTIVE_DRAFT", version__lt=added.version
        )
        .order_by("-version")
        .first()
    )
    added.delete()
    if previous is not None:
        previous.is_active = True
        previous.save(update_fields=["is_active", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("ai", "0025_coaching_prompt_hide_question_ids")]

    operations = [
        migrations.RunPython(add_v4, remove_v4),
    ]
