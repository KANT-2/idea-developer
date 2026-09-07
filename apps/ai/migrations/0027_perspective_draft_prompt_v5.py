from django.db import migrations

# v4는 질문 "성격"(간결형 vs 설명형)만으로 분량을 나눴는데, 사용자가 한 축을
# 더 요청했다: 핵심 지표·MVP 범위·문제 정의처럼 PRD 성패에 직접 영향을 주는
# 핵심 질문은 다른 설명형 질문보다 더 신경 써서 쓰라는 것.
#
# 검증: 실제 호출로 확인 — 핵심 MVP 범위(핵심 기능·우선순위)와 성공 지표
# (가치 지표 정의) 질문이 다른 설명형 질문보다 눈에 띄게 길어졌고
# (192자→209자, 192자→213자 등), 프로젝트명 같은 간결형 질문은 여전히 짧게
# 유지됐다. 등장하는 수치는 전부 기존 답변에서 인용한 것뿐이었다.

ANCHOR = (
    "짧게 답해도 되는 질문을 억지로 늘리거나, 설명이 필요한 질문을 한두 문장으로 "
    "짧게 끝내지 마세요."
)

IMPORTANCE_RULE = (
    " 그중에서도 핵심 지표, MVP 범위, 문제 정의처럼 PRD의 방향성과 실행 "
    "가능성에 직접적인 영향을 주는 핵심 질문은 다른 설명형 질문보다 더 "
    "신경 써서 작성하세요 — 필요하다면 두 문단을 넘어서더라도 근거와 "
    "고려사항을 충분히 담으세요. 반대로 부가 정보에 가까운 질문까지 억지로 "
    "핵심 질문처럼 늘리지 마세요."
)


def add_v5(apps, schema_editor):
    AiPrompt = apps.get_model("ai", "AiPrompt")
    current = AiPrompt.objects.filter(feature_type="PRD_PERSPECTIVE_DRAFT", is_active=True).first()
    if current is None or IMPORTANCE_RULE in current.system_instructions:
        return
    if ANCHOR not in current.system_instructions:
        return
    instructions = current.system_instructions.replace(ANCHOR, ANCHOR + IMPORTANCE_RULE, 1)
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


def remove_v5(apps, schema_editor):
    AiPrompt = apps.get_model("ai", "AiPrompt")
    added = (
        AiPrompt.objects.filter(feature_type="PRD_PERSPECTIVE_DRAFT", is_active=True)
        .order_by("-version")
        .first()
    )
    if added is None or IMPORTANCE_RULE not in added.system_instructions:
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
    dependencies = [("ai", "0026_perspective_draft_prompt_v4")]

    operations = [
        migrations.RunPython(add_v5, remove_v5),
    ]
