# ruff: noqa: E501

from django.db import migrations, models
from django.utils import timezone

# Each tuple is (position in the previous confirmed template, revised prompt).
# A null source creates a genuinely new question instead of reusing an unrelated answer.
QUESTIONS = {
    "new_product": {
        "프로젝트 요약": [
            (1, "프로젝트 이름과 한 문장 소개를 작성해 주세요."),
            (3, "어떤 사용자의 어떤 문제를 해결하려고 하나요?"),
            (4, "사용자가 얻을 수 있는 가장 큰 가치는 무엇인가요?"),
            (5, "첫 번째 버전에서는 어디까지 만들 예정인가요?"),
        ],
        "서비스 목표 및 핵심 가치": [
            (1, "이 서비스로 이루고 싶은 목표는 무엇인가요?"),
            (2, "서비스를 사용하면 사용자의 생활이나 업무가 어떻게 좋아지나요?"),
            (3, "기존 서비스나 해결 방법과 비교했을 때 가장 큰 차이점은 무엇인가요?"),
            (None, "서비스를 만들 때 반드시 지키고 싶은 핵심 가치는 무엇인가요?"),
        ],
        "추진 배경 및 기회": [
            (1, "이 문제를 발견한 계기와 지금 해결해야 하는 이유는 무엇인가요?"),
            (3, "기존 서비스나 해결 방법에는 어떤 불편이 있나요?"),
            (4, "사용자 조사나 참고 자료를 통해 무엇을 확인했나요?"),
            (6, "아직 확인되지 않아 검증이 필요한 가정은 무엇인가요?"),
        ],
        "핵심 타겟 및 이용 상황": [
            (1, "가장 먼저 사용할 사람은 누구이며, 그 사용자를 선택한 이유는 무엇인가요?"),
            (5, "사용자는 어떤 상황에서 이 서비스가 필요하고, 현재는 어떻게 해결하고 있나요?"),
            (7, "현재 해결 방법에서 가장 불편한 점은 무엇인가요?"),
            (8, "사용자가 서비스를 통해 최종적으로 얻고 싶은 결과는 무엇인가요?"),
        ],
        "문제 정의 및 솔루션 가설": [
            (
                2,
                "어떤 사용자가, 어떤 상황에서, 무엇을 하려 하지만, 무엇 때문에 어려운지 작성해 주세요.",
            ),
            (3, "이 문제가 사용자에게 어떤 영향을 주며, 꼭 해결해야 하는 이유는 무엇인가요?"),
            (4, "어떤 해결 방법을 제공하면 사용자의 행동이나 결과가 좋아질까요?"),
            (5, "가장 먼저 확인할 가정과 그 가정을 검증할 방법은 무엇인가요?"),
        ],
        "핵심 MVP 범위": [
            (
                1,
                "사용자가 서비스를 발견한 순간부터 핵심 기능을 완료할 때까지의 과정을 작성해 주세요.",
            ),
            (2, "반드시 만들 기능, 가능하면 만들 기능, 이번에는 만들지 않을 기능을 구분해 주세요."),
            (3, "입력 제한, 오류 처리, 권한, 데이터 보관 및 삭제 정책을 작성해 주세요."),
            (6, "사용할 기술 스택, 기술적 제약과 기능 완료 기준을 작성해 주세요."),
            (7, "관련 화면 설계, 와이어프레임과 상세 기능 명세는 어디에서 확인할 수 있나요?"),
        ],
        "성공 지표 및 검증 계획": [
            (1, "서비스 이용 여부와 사용자가 원하는 결과를 얻었는지 어떤 지표로 확인하나요?"),
            (3, "사용자 만족도와 의견은 어떤 방법으로 확인하나요?"),
            (4, "목표를 달성했을 때 다음 단계는 무엇인가요?"),
            (5, "목표에 미달했을 때 다시 확인하거나 수정할 가정은 무엇인가요?"),
        ],
    },
    "new_feature": {
        "기능 요약": [
            (1, "어떤 서비스에 어떤 이름의 기능을 추가하나요?"),
            (3, "이 기능이 필요한 이유와 해결하려는 문제는 무엇인가요?"),
            (4, "이 기능을 주로 사용할 사용자는 누구인가요?"),
            (5, "기존 서비스의 어느 화면이나 이용 과정에 연결되나요?"),
        ],
        "기능 목표 및 서비스 기여": [
            (1, "이 기능으로 이루고 싶은 목표는 무엇인가요?"),
            (2, "사용자는 이 기능을 통해 어떤 도움을 받나요?"),
            (3, "이 기능이 기존 서비스의 목표에 어떻게 기여하나요?"),
            (4, "기능 사용 후 사용자의 행동이 어떻게 달라지기를 기대하나요?"),
        ],
        "추가 배경 및 필요성": [
            (1, "현재 비슷한 기능이나 해결 과정은 어떻게 작동하나요?"),
            (2, "현재 방식으로 해결하지 못하는 문제는 무엇인가요?"),
            (3, "사용자 요청이나 데이터에서 확인한 근거는 무엇인가요?"),
            (
                5,
                "다른 해결 방법도 검토했다면, 새 기능을 선택한 이유와 지금 개발해야 하는 이유는 무엇인가요?",
            ),
        ],
        "기능 이용 대상 및 진입 맥락": [
            (1, "기존 사용자 중 누가 어떤 상황에서 이 기능을 가장 많이 사용할까요?"),
            (3, "사용자는 어디에서 기능을 발견하고, 어떤 일을 완료하려고 하나요?"),
            (5, "기능을 사용하기 위해 필요한 권한이나 사전 조건은 무엇인가요?"),
            (6, "기능을 이용할 수 없거나 필요한 데이터가 없을 때 무엇을 보여주나요?"),
        ],
        "문제 정의 및 기능 가설": [
            (1, "사용자가 현재 하는 행동과 그 행동을 어렵게 만드는 원인은 무엇인가요?"),
            (3, "새 기능으로 해결해야 할 가장 중요한 문제는 무엇인가요?"),
            (5, "어떤 기능을 제공하면 사용자 행동과 서비스 성과가 어떻게 달라질까요?"),
            (7, "이 가설이 맞는지 어떤 방법으로 확인할 예정인가요?"),
        ],
        "신규 기능 범위 및 기존 서비스 연계": [
            (1, "새 기능을 포함한 전체 이용 과정과 변경되는 화면을 작성해 주세요."),
            (2, "반드시 만들 기능, 가능하면 만들 기능, 만들지 않을 기능을 구분해 주세요."),
            (4, "읽거나 변경하는 기존 데이터와 조회·수정 권한을 작성해 주세요."),
            (
                6,
                "기존 데이터 적용, 연결 데이터 변경·삭제, 중복 요청과 오류 상황은 어떻게 처리하나요?",
            ),
            (10, "이용 제한, 완료 기준, 기술 스택과 중요한 기술적 제약은 무엇인가요?"),
            (11, "관련 화면 설계, 기능 명세와 정책 문서는 어디에서 확인할 수 있나요?"),
        ],
        "성공 지표 및 출시 후 검증": [
            (1, "기능 사용 여부와 실제 성과를 어떤 지표로 확인하나요?"),
            (3, "기존 서비스에 문제가 생기지 않았는지 어떤 지표로 확인하나요?"),
            (4, "사용자 의견은 어떤 질문과 방법으로 수집하나요?"),
            (5, "처음 공개할 사용자와 전체 공개 조건은 무엇인가요?"),
            (7, "어떤 문제가 발생하면 기능을 수정하거나 중단하나요?"),
        ],
    },
    "improvement": {
        "개선 프로젝트 요약": [
            (1, "어떤 서비스의 어떤 기능을 개선하나요?"),
            (3, "현재 발생하는 문제는 무엇인가요?"),
            (4, "무엇을 어떻게 바꿀 예정인가요?"),
            (5, "개선 후에도 그대로 유지해야 할 기능과 정책은 무엇인가요?"),
        ],
        "개선 목표 및 기대 효과": [
            (1, "이번 개선으로 이루고 싶은 목표는 무엇인가요?"),
            (2, "사용자와 서비스 운영 측면에서 각각 무엇이 좋아지나요?"),
            (4, "이번 개선에서 해결하지 않을 문제는 무엇인가요?"),
            (None, "개선이 성공했다고 판단할 수 있는 가장 중요한 변화는 무엇인가요?"),
        ],
        "현황 및 개선 근거": [
            (1, "현재 기능은 어떻게 작동하며, 어느 과정에서 문제가 자주 발생하나요?"),
            (2, "현재 성과나 문제의 크기를 보여주는 수치 또는 기준은 무엇인가요?"),
            (4, "사용자들이 반복해서 말하는 불편은 무엇인가요?"),
            (5, "확인된 원인과 아직 검증이 필요한 원인을 구분해 주세요."),
            (7, "다른 개선 사항보다 먼저 진행해야 하는 이유는 무엇인가요?"),
        ],
        "영향받는 사용자 및 이용 상황": [
            (1, "이 문제를 가장 자주 겪는 사용자는 누구인가요?"),
            (2, "어떤 조건이나 상황에서 문제가 발생하나요?"),
            (3, "사용자는 현재 이 문제에 어떻게 대응하며, 목표 달성에 얼마나 방해받고 있나요?"),
            (
                5,
                "기존 방식에 익숙한 사용자에게 미칠 영향과 비교 대상 사용자 구분 방법을 작성해 주세요.",
            ),
        ],
        "문제 원인 및 개선 가설": [
            (1, "현재 나타나는 문제와 사용자·서비스에 미치는 영향을 구체적으로 작성해 주세요."),
            (4, "검토한 개선 방법과 최종 방법을 선택한 이유는 무엇인가요?"),
            (6, "무엇을 바꾸면 사용자의 행동과 성과가 어떻게 좋아질까요?"),
            (7, "개선 효과를 확인하는 방법과 방향이 잘못됐다고 판단할 기준은 무엇인가요?"),
        ],
        "개선 범위 및 변경 명세": [
            (1, "현재 상태와 개선 후 상태, 개선 후 정상 이용 과정을 비교해 주세요."),
            (5, "변경할 화면·문구·작동 방식과 그대로 유지할 기능을 작성해 주세요."),
            (3, "오류나 검증 실패를 어떻게 처리하며, 영향을 받는 다른 기능은 무엇인가요?"),
            (7, "기존 데이터 변경·이관과 사용자 안내가 필요한가요?"),
            (
                9,
                "문제가 생겼을 때 이전 상태로 되돌리는 방법과 완료 후 다시 확인할 기능은 무엇인가요?",
            ),
            (11, "기술 스택과 제약, 관련 화면·기능 명세·테스트 목록은 어디에서 확인할 수 있나요?"),
        ],
        "개선 성과 및 검증 계획": [
            (1, "핵심 지표와 줄이고 싶은 문제의 현재값·목표값은 무엇인가요?"),
            (3, "개선 후에도 나빠지면 안 되는 지표는 무엇인가요?"),
            (4, "사용자 의견은 어떤 질문으로, 언제 확인하나요?"),
            (6, "전후 비교 또는 A/B 테스트는 어떻게 진행하며 어떤 사용자 환경 차이를 확인하나요?"),
            (8, "어떤 결과가 나오면 전체 적용하고, 어떤 결과가 나오면 추가 개선하거나 되돌리나요?"),
        ],
    },
}


def _rebuild_template_questions(question_model, section, specs):
    existing = list(question_model.objects.filter(section=section).order_by("position", "id"))
    by_position = {question.position: question for question in existing}
    for question in existing:
        question_model.objects.filter(pk=question.pk).update(position=1_000_000 + question.pk)

    retained_ids = set()
    for position, (source_position, prompt) in enumerate(specs, start=1):
        question = by_position.get(source_position) if source_position is not None else None
        if question is None or question.pk in retained_ids:
            question = question_model.objects.create(
                section=section,
                prompt=prompt,
                position=position,
            )
            retained_ids.add(question.pk)
        else:
            retained_ids.add(question.pk)
            question_model.objects.filter(pk=question.pk).update(
                prompt=prompt,
                position=position,
            )
    question_model.objects.filter(section=section).exclude(pk__in=retained_ids).exclude(
        position__lte=len(specs)
    ).delete()


def _rebuild_prd_questions(question_model, section, specs, changed_at):
    existing = list(
        question_model.objects.filter(section=section, is_deleted=False).order_by("position", "id")
    )
    by_position = {question.position: question for question in existing}
    for question in existing:
        question_model.objects.filter(pk=question.pk).update(position=1_000_000 + question.pk)

    retained_ids = set()
    for position, (source_position, prompt) in enumerate(specs, start=1):
        question = by_position.get(source_position) if source_position is not None else None
        if question is None or question.pk in retained_ids:
            question = question_model.objects.create(
                section=section,
                prompt=prompt,
                position=position,
            )
            retained_ids.add(question.pk)
        else:
            retained_ids.add(question.pk)
            question_model.objects.filter(pk=question.pk).update(
                prompt=prompt,
                position=position,
                version=models.F("version") + 1,
            )

    question_model.objects.filter(section=section, is_deleted=False).exclude(
        pk__in=retained_ids
    ).update(
        is_deleted=True,
        deleted_at=changed_at,
        version=models.F("version") + 1,
    )


def compact_template_questions(apps, schema_editor):
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
        for title, specs in sections.items():
            template_section = template_sections.get(title)
            if template_section is not None:
                _rebuild_template_questions(template_question_model, template_section, specs)

        for section in section_model.objects.filter(prd__prd_type=prd_type, title__in=sections):
            _rebuild_prd_questions(question_model, section, sections[section.title], changed_at)


class Migration(migrations.Migration):
    dependencies = [("prds", "0013_participant_comment_versions")]

    operations = [
        migrations.RunPython(compact_template_questions, migrations.RunPython.noop),
    ]
