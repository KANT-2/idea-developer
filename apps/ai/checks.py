from django.conf import settings
from django.core import checks


@checks.register(checks.Tags.security, deploy=True)
def gemini_key_is_configured(app_configs, **kwargs):
    if (
        not settings.DEBUG
        and settings.AI_PROVIDER_CLASS == "apps.ai.gemini.GeminiAiProvider"
        and not settings.GEMINI_API_KEY.strip()
    ):
        return [
            checks.Error(
                "Gemini AI provider is enabled without a GEMINI_API_KEY.",
                hint="Set GEMINI_API_KEY in the deployment secret store.",
                id="ai.E001",
            )
        ]
    return []
