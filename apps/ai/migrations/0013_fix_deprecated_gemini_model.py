from django.db import migrations

# gemini-2.5-flash-lite는 Google이 신규 사용자에게 더 이상 제공하지 않아
# 실제 호출 시 404 provider_model_not_found로 실패한다. 0009/0010이 심은
# COACHING·PRD_EVALUATION 두 프롬프트 모두 이 모델명을 쓰고 있었다.
# 실제 API 호출로 재현해 확인했고, Google이 안내하는 대체 모델로 바꾼다.
OLD_MODEL = "gemini-2.5-flash-lite"
NEW_MODEL = "gemini-3.5-flash-lite"


def fix_model(apps, schema_editor):
    AiPrompt = apps.get_model("ai", "AiPrompt")
    AiPrompt.objects.filter(model=OLD_MODEL).update(model=NEW_MODEL)


def revert_model(apps, schema_editor):
    AiPrompt = apps.get_model("ai", "AiPrompt")
    AiPrompt.objects.filter(model=NEW_MODEL).update(model=OLD_MODEL)


class Migration(migrations.Migration):
    dependencies = [("ai", "0012_coaching_prompt_declined_rule")]

    operations = [
        migrations.RunPython(fix_model, revert_model),
    ]
