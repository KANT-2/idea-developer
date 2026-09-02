from django.conf import settings
from django.core import checks
from django.urls import Resolver404, resolve


@checks.register(checks.Tags.security, deploy=True)
def debug_login_not_deployed(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    try:
        resolve("/accounts/dev/login/")
    except Resolver404:
        return []
    return [
        checks.Error(
            "DEBUG test login URL is registered while DEBUG is false.",
            id="accounts.E001",
        )
    ]


@checks.register(checks.Tags.security, deploy=True)
def production_email_backend_is_real(app_configs, **kwargs):
    unsafe_backends = {
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.dummy.EmailBackend",
    }
    if not settings.DEBUG and settings.EMAIL_BACKEND in unsafe_backends:
        return [
            checks.Error(
                "A non-delivery email backend is configured for production OTP login.",
                hint="Configure a production email backend before deployment.",
                id="accounts.E002",
            )
        ]
    return []
