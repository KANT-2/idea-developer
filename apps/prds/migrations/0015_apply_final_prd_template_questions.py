# ruff: noqa: E501

from django.db import migrations, models
from django.utils import timezone

QUESTIONS = {
    "new_product": {
        "프로젝트 요약": [
            "프로젝트 이름은 무엇인가요?",
            "이 프로젝트를 한 문장으로 소개하면 무엇인가요?",
            "어떤 사용자의 어떤 문제를 해결하려고 하나요?",
            "사용자가 얻을 수 있는 가장 큰 가치는 무엇인가요?",
            "첫 번째 버전에서는 어디까지 만들 예정인가요?",
        ],
        "서비스 목표 및 핵심 가치": [
            "이 서비스로 이루고 싶은 목표는 무엇인가요?",
            "서비스를 사용하면 사용자의 생활이나 업무가 어떻게 좋아지나요?",
            "기존 해결 방법과 비교했을 때 이 서비스를 선택할 가장 큰 이유는 무엇인가요?",
        ],
        "추진 배경 및 기회": [
            "이 문제를 발견한 계기와 지금 해결해야 하는 이유는 무엇인가요?",
            "기존 서비스나 해결 방법에는 어떤 불편이 있나요?",
            "사용자 조사·데이터·시장 변화 등에서 이 문제를 뒷받침하는 근거가 있나요?",
            "아직 확인되지 않아 검증이 필요한 가정은 무엇인가요?",
        ],
        "핵심 타겟 및 이용 상황": [
            "가장 먼저 사용할 사람은 누구이며, 그 사용자를 선택한 이유는 무엇인가요?",
            "이번 버전에서 우선하지 않을 사용자는 누구인가요?",
            "사용자는 어떤 상황에서 이 서비스가 필요하고, 현재는 어떻게 해결하고 있나요?",
            "현재 해결 방법에서 가장 불편한 점은 무엇인가요?",
            "사용자가 서비스를 통해 최종적으로 얻고 싶은 결과는 무엇인가요?",
        ],
        "문제 정의 및 솔루션 가설": [
            "어떤 사용자가 어떤 상황에서 무엇을 하려 하지만, 어떤 어려움 때문에 목표를 이루지 못하고 있나요?",
            "이 문제가 사용자에게 어떤 영향을 주며, 꼭 해결해야 하는 이유는 무엇인가요?",
            "어떤 해결 방법을 제공하면 사용자의 행동이나 결과가 좋아질까요?",
            "가장 먼저 확인할 가정과 그 가정을 검증할 방법은 무엇인가요?",
        ],
        "핵심 MVP 범위": [
            "사용자가 서비스를 시작해 핵심 결과를 얻기까지 어떤 과정을 거치나요?",
            "반드시 만들 기능, 가능하면 만들 기능, 이번에는 만들지 않을 기능을 구분해 주세요.",
            "입력 제한, 권한, 데이터 처리, 오류 상황 등 반드시 정해야 할 정책은 무엇인가요?",
            "어떤 상태가 되면 이 기능을 정상적으로 완성했다고 판단할 수 있나요?",
            "관련 화면 설계, 와이어프레임과 상세 기능 명세는 어디에서 확인할 수 있나요?",
        ],
        "성공 지표 및 검증 계획": [
            "사용자가 핵심 기능을 실제로 사용하고 원하는 결과를 얻었는지 어떤 지표로 확인할 수 있나요?",
            "사용자 만족도와 의견은 어떤 방법으로 확인하나요?",
            "목표를 달성했을 때 다음 단계는 무엇인가요?",
            "목표에 미달했을 때 다시 확인하거나 수정할 가정은 무엇인가요?",
        ],
    },
    "new_feature": {
        "기능 요약": [
            "어떤 서비스에 기능을 추가하나요?",
            "추가하려는 기능의 이름은 무엇인가요?",
            "이 기능이 필요한 이유와 해결하려는 문제는 무엇인가요?",
            "이 기능을 주로 사용할 사용자는 누구인가요?",
            "기존 서비스의 어느 화면이나 이용 과정에 연결되나요?",
        ],
        "기능 목표 및 서비스 기여": [
            "이 기능으로 이루고 싶은 목표는 무엇인가요?",
            "사용자는 이 기능을 통해 어떤 도움을 받나요?",
            "이 기능이 기존 서비스의 목표에 어떻게 기여하나요?",
            "기능 사용 후 사용자의 행동이 어떻게 달라지기를 기대하나요?",
        ],
        "추가 배경 및 필요성": [
            "현재 비슷한 기능이나 해결 과정은 어떻게 작동하나요?",
            "현재 방식으로 해결하지 못하는 문제는 무엇인가요?",
            "사용자 요청이나 데이터에서 확인한 근거는 무엇인가요?",
            "다른 해결 방법 대신 새 기능을 추가하는 것이 가장 적절한 이유는 무엇인가요?",
        ],
        "기능 이용 대상 및 진입 맥락": [
            "기존 사용자 중 누가 어떤 상황에서 이 기능을 가장 많이 사용할까요?",
            "사용자는 어디에서 기능을 발견하고, 어떤 일을 완료하려고 하나요?",
            "기능을 사용하기 위해 필요한 권한이나 사전 조건은 무엇인가요?",
            "기능을 이용할 수 없거나 필요한 데이터가 없을 때 무엇을 보여주나요?",
        ],
        "문제 정의 및 기능 가설": [
            "사용자가 현재 하는 행동과 그 행동을 어렵게 만드는 원인은 무엇인가요?",
            "위 문제 중 새 기능으로 반드시 해결해야 하는 핵심 문제는 무엇인가요?",
            "어떤 기능을 제공하면 사용자 행동과 서비스 성과가 어떻게 달라질까요?",
            "이 가설이 맞는지 어떤 방법으로 확인할 예정인가요?",
        ],
        "신규 기능 범위 및 기존 서비스 연계": [
            "새 기능을 포함하면 기존 이용 흐름과 어떤 화면이 달라지나요?",
            "반드시 만들 기능, 가능하면 만들 기능, 이번에는 만들지 않을 기능은 무엇인가요?",
            "이 기능은 어떤 기존 데이터를 사용하며, 누가 조회하거나 변경할 수 있나요?",
            "기존 기록·데이터 변경·삭제·중복 요청 등에서 정해야 할 정책은 무엇인가요?",
            "빈 상태·오류·이용 제한과 기능 완료 기준은 무엇인가요?",
            "관련 화면 설계, 기능 명세, 정책 문서는 어디에서 확인할 수 있나요?",
        ],
        "성공 지표 및 출시 후 검증": [
            "기능 사용 여부와 실제 성과를 어떤 지표로 확인하나요?",
            "기존 서비스에 문제가 생기지 않았는지 어떤 지표로 확인하나요?",
            "사용자 의견은 어떤 질문과 방법으로 수집하나요?",
            "처음 공개할 사용자와 전체 공개 조건은 무엇인가요?",
            "어떤 문제가 발생하면 기능을 수정하거나 중단하나요?",
        ],
    },
    "improvement": {
        "개선 프로젝트 요약": [
            "어떤 기능을 개선하려고 하나요?",
            "현재 발생하는 문제는 무엇인가요?",
            "무엇을 어떻게 바꿀 예정인가요?",
            "개선 후에도 그대로 유지해야 할 기능과 정책은 무엇인가요?",
        ],
        "개선 목표 및 기대 효과": [
            "이번 개선으로 이루고 싶은 목표는 무엇인가요?",
            "사용자에게 무엇이 좋아지나요?",
            "서비스나 운영 측면에서 무엇이 좋아지나요?",
            "이번 개선에서 해결하지 않을 문제는 무엇인가요?",
        ],
        "현황 및 개선 근거": [
            "현재 기능은 어떻게 작동하며, 어느 과정에서 문제가 자주 발생하나요?",
            "현재 성과나 문제의 크기를 보여주는 수치 또는 기준은 무엇인가요?",
            "사용자들이 반복해서 말하는 불편은 무엇인가요?",
            "확인된 원인과 아직 검증이 필요한 원인을 구분해 주세요.",
            "다른 개선 사항보다 먼저 진행해야 하는 이유는 무엇인가요?",
        ],
        "영향받는 사용자 및 이용 상황": [
            "이 문제를 가장 자주 겪는 사용자는 누구인가요?",
            "어떤 조건이나 상황에서 문제가 발생하나요?",
            "사용자는 현재 이 문제에 어떻게 대응하며, 목표 달성에 얼마나 방해받고 있나요?",
            "기존 방식에 익숙한 사용자에게 어떤 영향이 있으며, 개선 효과를 비교할 때 어떤 사용자군을 나눠 봐야 하나요?",
        ],
        "문제 원인 및 개선 가설": [
            "현재 문제가 발생하는 가장 중요한 원인 또는 원인 가설은 무엇인가요?",
            "어떤 개선 방법들을 검토했으며, 최종 방법을 선택한 이유는 무엇인가요?",
            "무엇을 바꾸면 사용자의 행동과 성과가 어떻게 좋아질까요?",
            "개선 효과를 어떻게 확인하며, 어떤 결과가 나오면 가설을 다시 검토해야 하나요?",
        ],
        "개선 범위 및 변경 명세": [
            "현재와 개선 후에는 무엇이 달라지며, 개선 후 사용자는 어떤 과정을 거치게 되나요?",
            "변경할 화면·문구·작동 방식과 그대로 유지할 기능을 작성해 주세요.",
            "오류나 검증 실패를 어떻게 처리하며, 영향을 받는 다른 기능은 무엇인가요?",
            "기존 데이터 변경·이관과 사용자 안내가 필요한가요?",
            "문제가 생겼을 때 이전 상태로 되돌리는 방법과 완료 후 다시 확인할 기능은 무엇인가요?",
            "관련 화면 설계, 기능 명세, 기술적 제약과 테스트 목록은 어디에서 확인할 수 있나요?",
        ],
        "개선 성과 및 검증 계획": [
            "핵심 지표와 줄이고 싶은 문제의 현재값·목표값은 무엇인가요?",
            "개선 후에도 나빠지면 안 되는 지표는 무엇인가요?",
            "사용자 의견은 어떤 질문으로, 언제 확인하나요?",
            "전후 비교 또는 A/B 테스트는 어떻게 진행하며 어떤 사용자 환경 차이를 확인하나요?",
            "어떤 결과가 나오면 전체 적용하고, 어떤 결과가 나오면 추가 개선하거나 되돌리나요?",
        ],
    },
}


def _replace_template_questions(question_model, section, prompts):
    existing = list(question_model.objects.filter(section=section).order_by("position", "id"))
    for question in existing:
        question_model.objects.filter(pk=question.pk).update(position=1_000_000 + question.pk)

    retained_ids = []
    for position, prompt in enumerate(prompts, start=1):
        if position <= len(existing):
            question = existing[position - 1]
            question_model.objects.filter(pk=question.pk).update(prompt=prompt, position=position)
        else:
            question = question_model.objects.create(
                section=section,
                prompt=prompt,
                position=position,
            )
        retained_ids.append(question.pk)

    question_model.objects.filter(section=section).exclude(pk__in=retained_ids).delete()


def _replace_prd_questions(question_model, section, prompts, changed_at):
    existing = list(
        question_model.objects.filter(section=section, is_deleted=False).order_by("position", "id")
    )
    for question in existing:
        question_model.objects.filter(pk=question.pk).update(position=1_000_000 + question.pk)

    retained_ids = []
    for position, prompt in enumerate(prompts, start=1):
        if position <= len(existing):
            question = existing[position - 1]
            question_model.objects.filter(pk=question.pk).update(
                prompt=prompt,
                position=position,
                version=models.F("version") + 1,
            )
        else:
            question = question_model.objects.create(
                section=section,
                prompt=prompt,
                position=position,
            )
        retained_ids.append(question.pk)

    question_model.objects.filter(section=section, is_deleted=False).exclude(
        pk__in=retained_ids
    ).update(
        is_deleted=True,
        deleted_at=changed_at,
        version=models.F("version") + 1,
    )


def apply_final_questions(apps, schema_editor):
    template_model = apps.get_model("prds", "PrdTemplate")
    template_question_model = apps.get_model("prds", "PrdTemplateQuestion")
    section_model = apps.get_model("prds", "PrdSection")
    question_model = apps.get_model("prds", "PrdQuestion")
    changed_at = timezone.now()

    templates = {
        template.prd_type: template
        for template in template_model.objects.prefetch_related("sections__questions")
    }
    for prd_type, sections in QUESTIONS.items():
        template = templates.get(prd_type)
        if template is None:
            continue
        template_sections = {section.title: section for section in template.sections.all()}
        for title, prompts in sections.items():
            template_section = template_sections.get(title)
            if template_section is not None:
                _replace_template_questions(template_question_model, template_section, prompts)

        for section in section_model.objects.filter(prd__prd_type=prd_type, title__in=sections):
            _replace_prd_questions(question_model, section, sections[section.title], changed_at)


class Migration(migrations.Migration):
    dependencies = [("prds", "0014_compact_prd_template_questions")]

    operations = [
        migrations.RunPython(apply_final_questions, migrations.RunPython.noop),
    ]
