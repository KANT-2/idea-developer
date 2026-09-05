from django.conf import settings
from django.db import transaction

from apps.integration.context import is_admin_parent_identity, is_tutor_parent_identity
from apps.integration.repository import get_default_integration_repository


def runtime_settings(request):
    return {
        "react_cdn_url": settings.REACT_CDN_URL,
        "react_dom_cdn_url": settings.REACT_DOM_CDN_URL,
        "polling_interval_ms": settings.POLLING_INTERVAL_MS,
    }


def session_identity(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"session_identity": None}

    email = getattr(user, "email_snapshot", "") or ""
    fallback_name = email.split("@", 1)[0] if email else "로그인 사용자"
    identity = {
        "display_name": fallback_name,
        "email": email or "이메일 정보 없음",
        "role_label": "수강생",
    }
    external_user_id = getattr(user, "external_user_id", None)
    if external_user_id is None:
        return {"session_identity": identity}

    try:
        # Optional identity decoration must not leave a PostgreSQL request/test
        # transaction unusable when the parent-owned VIEW is unavailable.
        repository = get_default_integration_repository()
        database_alias = getattr(repository, "database_alias", None)
        if isinstance(database_alias, str) and database_alias:
            with transaction.atomic(using=database_alias):
                parent_user = repository.get_user(external_user_id)
                summary = repository.get_user_summaries(user_ids=(external_user_id,)).get(
                    external_user_id
                )
        else:
            parent_user = repository.get_user(external_user_id)
            summary = repository.get_user_summaries(user_ids=(external_user_id,)).get(
                external_user_id
            )
    except Exception:
        parent_user = None
        summary = None

    if parent_user:
        if summary:
            identity["display_name"] = summary.display_name
        identity["email"] = parent_user.primary_email or parent_user.user_email or identity["email"]
        if is_tutor_parent_identity(parent_user.parent_role):
            identity["role_label"] = "튜터"
        elif is_admin_parent_identity(
            parent_role=parent_user.parent_role,
            is_staff=parent_user.is_staff,
            is_superuser=parent_user.is_superuser,
        ):
            identity["role_label"] = "관리자"

    return {"session_identity": identity}
