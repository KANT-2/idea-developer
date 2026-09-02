from __future__ import annotations

import uuid

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models

from .managers import LocalUserMappingManager


class LocalUserMapping(AbstractBaseUser):
    """Session principal mapping only; parent VIEWs remain the user source of truth."""

    external_user_id = models.BigIntegerField(unique=True)
    email_snapshot = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LocalUserMappingManager()

    USERNAME_FIELD = "external_user_id"
    EMAIL_FIELD = "email_snapshot"

    class Meta:
        db_table = "idea_local_user_mapping"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(password__startswith="!"),
                name="local_user_password_unusable",
            )
        ]

    @property
    def is_staff(self):
        return False

    @property
    def is_superuser(self):
        return False

    def has_perm(self, perm, obj=None):
        return False

    def has_module_perms(self, app_label):
        return False

    def save(self, *args, **kwargs):
        if self.has_usable_password():
            self.set_unusable_password()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"external-user:{self.external_user_id}"


class LoginOtpChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    normalized_email = models.EmailField(db_index=True)
    external_user_id = models.BigIntegerField(null=True, blank=True)
    code_hash = models.CharField(max_length=255)
    ip_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "idea_login_otp_challenge"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(failed_attempts__lte=5),
                name="login_otp_failed_attempts_lte_5",
            )
        ]
        indexes = [
            models.Index(
                fields=["normalized_email", "created_at"],
                name="login_otp_email_created_idx",
            ),
            models.Index(
                fields=["ip_hash", "created_at"],
                name="login_otp_ip_created_idx",
            ),
        ]


class LoginAuditLog(models.Model):
    class Event(models.TextChoices):
        OTP_REQUESTED = "otp_requested", "OTP requested"
        LOGIN_SUCCESS = "login_success", "Login success"
        LOGIN_FAILURE = "login_failure", "Login failure"
        LOGOUT = "logout", "Logout"
        DEBUG_LOGIN = "debug_login", "Debug login"

    external_user_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    event = models.CharField(max_length=32, choices=Event.choices)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    user_agent_summary = models.CharField(max_length=255, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "idea_login_audit_log"
        ordering = ["-occurred_at", "-id"]
