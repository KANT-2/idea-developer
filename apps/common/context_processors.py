from django.conf import settings
from django.db import DatabaseError

from apps.integration.models import AxUserTeamLoginView


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
        row = (
            AxUserTeamLoginView.objects.using(settings.INTEGRATION_DB_ALIAS)
            .filter(user_id=external_user_id)
            .values(
                "display_name_snapshot",
                "first_name",
                "last_name",
                "primary_email",
                "user_email",
                "role",
                "is_staff",
                "is_superuser",
            )
            .first()
        )
    except DatabaseError:
        row = None

    if row:
        full_name = " ".join(
            part.strip() for part in (row["first_name"], row["last_name"]) if part and part.strip()
        )
        identity["display_name"] = (
            (row["display_name_snapshot"] or "").strip() or full_name or fallback_name
        )
        identity["email"] = row["primary_email"] or row["user_email"] or identity["email"]
        parent_role = (row["role"] or "").strip().lower()
        tutor_roles = {"tutor", "teacher", "mentor", "instructor"}
        if row["is_staff"] or row["is_superuser"] or parent_role in tutor_roles:
            identity["role_label"] = "튜터"

    return {"session_identity": identity}
