from .base import *  # noqa: F403

DEBUG = True
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Temporary local fixture used only when the parent VIEW database is moving or offline.
DEV_INTEGRATION_FALLBACK = env_bool("DEV_INTEGRATION_FALLBACK", True)  # noqa: F405
DEV_INTEGRATION_USERS = [
    {"user_id": 2, "user_email": "crasnec+tutor@gmail.com", "primary_email": "crasnec+tutor@gmail.com", "first_name": "개발", "last_name": "튜터", "display_name_snapshot": "개발 튜터", "role": "tutor", "approval_status": "approved", "is_active": True, "is_staff": True, "is_superuser": False},
    {"user_id": 21, "user_email": "minjun@example.test", "primary_email": "minjun@example.test", "first_name": "민준", "last_name": "김", "display_name_snapshot": "김민준", "role": "student", "approval_status": "approved", "is_active": True, "is_staff": False, "is_superuser": False},
    {"user_id": 22, "user_email": "seoyeon@example.test", "primary_email": "seoyeon@example.test", "first_name": "서연", "last_name": "이", "display_name_snapshot": "이서연", "role": "student", "approval_status": "approved", "is_active": True, "is_staff": False, "is_superuser": False},
    {"user_id": 23, "user_email": "jihoon@example.test", "primary_email": "jihoon@example.test", "first_name": "지훈", "last_name": "박", "display_name_snapshot": "박지훈", "role": "student", "approval_status": "approved", "is_active": True, "is_staff": False, "is_superuser": False},
    {"user_id": 24, "user_email": "lionel.messi@example.com", "primary_email": "lionel.messi@example.com", "first_name": "리오넬", "last_name": "메시", "display_name_snapshot": "리오넬 메시", "role": "student", "approval_status": "approved", "is_active": True, "is_staff": False, "is_superuser": False},
    {"user_id": 25, "user_email": "yujin@example.test", "primary_email": "yujin@example.test", "first_name": "유진", "last_name": "최", "display_name_snapshot": "최유진", "role": "student", "approval_status": "approved", "is_active": True, "is_staff": False, "is_superuser": False},
    {"user_id": 26, "user_email": "daeun@example.test", "primary_email": "daeun@example.test", "first_name": "다은", "last_name": "정", "display_name_snapshot": "정다은", "role": "student", "approval_status": "approved", "is_active": True, "is_staff": False, "is_superuser": False},
    {"user_id": 27, "user_email": "seojun@example.test", "primary_email": "seojun@example.test", "first_name": "서준", "last_name": "윤", "display_name_snapshot": "윤서준", "role": "student", "approval_status": "approved", "is_active": True, "is_staff": False, "is_superuser": False},
    {"user_id": 28, "user_email": "jimin@example.test", "primary_email": "jimin@example.test", "first_name": "지민", "last_name": "한", "display_name_snapshot": "한지민", "role": "student", "approval_status": "approved", "is_active": True, "is_staff": False, "is_superuser": False},
    {"user_id": 29, "user_email": "subin@example.test", "primary_email": "subin@example.test", "first_name": "수빈", "last_name": "오", "display_name_snapshot": "오수빈", "role": "student", "approval_status": "approved", "is_active": True, "is_staff": False, "is_superuser": False},
    {"user_id": 30, "user_email": "hyunwoo@example.test", "primary_email": "hyunwoo@example.test", "first_name": "현우", "last_name": "강", "display_name_snapshot": "강현우", "role": "student", "approval_status": "approved", "is_active": True, "is_staff": False, "is_superuser": False},
]
DEV_INTEGRATION_MEMBERSHIPS = []
