from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from apps.integration.repository import (
    LoginIdentity,
    get_default_integration_repository,
)

from .exceptions import (
    InvalidEmail,
    OtpAlreadyUsed,
    OtpAttemptLimit,
    OtpCooldown,
    OtpDeliveryUnavailable,
    OtpExpired,
    OtpInvalid,
    OtpRateLimited,
)
from .models import LocalUserMapping, LoginAuditLog, LoginOtpChallenge

logger = logging.getLogger(__name__)

UNIFORM_REQUEST_MESSAGE = "입력하신 이메일로 인증번호 발송을 처리했습니다."


@dataclass(frozen=True, slots=True)
class OtpRequestResult:
    challenge_id: str
    masked_email: str
    expires_in_seconds: int
    resend_after_seconds: int
    message: str = UNIFORM_REQUEST_MESSAGE


def normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidEmail("올바른 이메일 주소를 입력해 주세요.")
    normalized = (value or "").strip().lower()
    try:
        validate_email(normalized)
    except ValidationError as exc:
        raise InvalidEmail("올바른 이메일 주소를 입력해 주세요.") from exc
    return normalized


def mask_email(email: str) -> str:
    local, domain = email.split("@", 1)
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


def request_ip_hash(request) -> str:
    remote_addr = request.META.get("REMOTE_ADDR", "")
    return hmac.new(
        settings.SECRET_KEY.encode(),
        remote_addr.encode(),
        hashlib.sha256,
    ).hexdigest()


def user_agent_summary(request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")[:255]


def record_audit(request, event, *, external_user_id=None, details=None):
    return LoginAuditLog.objects.create(
        external_user_id=external_user_id,
        event=event,
        ip_hash=request_ip_hash(request),
        user_agent_summary=user_agent_summary(request),
        details=details or {},
    )


class OtpAuthenticationService:
    def __init__(self, repository=None):
        self.repository = repository or get_default_integration_repository()

    def request_code(self, request, email: str) -> OtpRequestResult:
        normalized_email = normalize_email(email)
        now = timezone.now()
        ip_hash = request_ip_hash(request)
        self._enforce_request_limits(normalized_email, ip_hash, now)

        identity = self.repository.find_login_identity(normalized_email)
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = now + timedelta(seconds=settings.OTP_EXPIRY_SECONDS)

        try:
            with transaction.atomic():
                challenge = LoginOtpChallenge.objects.create(
                    normalized_email=normalized_email,
                    external_user_id=identity.user_id if identity else None,
                    code_hash=make_password(code),
                    ip_hash=ip_hash,
                    expires_at=expires_at,
                )
                if identity:
                    send_mail(
                        subject="[Idea Developer] 로그인 인증번호",
                        message=(
                            f"인증번호는 {code}입니다. "
                            f"{settings.OTP_EXPIRY_SECONDS // 60}분 안에 입력해 주세요."
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[normalized_email],
                        fail_silently=False,
                    )
        except Exception as exc:
            logger.exception("OTP email delivery failed")
            raise OtpDeliveryUnavailable(
                "인증번호를 발송할 수 없습니다. 잠시 후 다시 시도해 주세요."
            ) from exc

        record_audit(
            request,
            LoginAuditLog.Event.OTP_REQUESTED,
            external_user_id=identity.user_id if identity else None,
        )
        return OtpRequestResult(
            challenge_id=str(challenge.id),
            masked_email=mask_email(normalized_email),
            expires_in_seconds=settings.OTP_EXPIRY_SECONDS,
            resend_after_seconds=settings.OTP_RESEND_COOLDOWN_SECONDS,
        )

    def verify_code(self, request, *, challenge_id, code: str) -> LocalUserMapping:
        now = timezone.now()
        code = (code or "").strip()
        failure = None
        user = None
        with transaction.atomic():
            try:
                challenge = LoginOtpChallenge.objects.select_for_update().get(pk=challenge_id)
            except (LoginOtpChallenge.DoesNotExist, ValidationError, ValueError) as exc:
                raise OtpInvalid("인증번호가 올바르지 않습니다.") from exc

            if challenge.used_at is not None:
                failure = OtpAlreadyUsed("이미 사용한 인증번호입니다.")
            elif challenge.expires_at <= now:
                self._audit_failure(request, challenge, "expired")
                failure = OtpExpired("인증번호가 만료되었습니다. 다시 요청해 주세요.")
            elif challenge.failed_attempts >= settings.OTP_MAX_FAILED_ATTEMPTS:
                failure = OtpAttemptLimit("인증번호 입력 가능 횟수를 초과했습니다.")
            else:
                valid_format = len(code) == 6 and code.isdigit()
                code_matches = valid_format and check_password(code, challenge.code_hash)
                identity = (
                    self.repository.get_login_identity(challenge.external_user_id)
                    if code_matches and challenge.external_user_id is not None
                    else None
                )
            if failure is None and (not code_matches or identity is None):
                challenge.failed_attempts += 1
                challenge.save(update_fields=["failed_attempts"])
                self._audit_failure(request, challenge, "invalid")
                if challenge.failed_attempts >= settings.OTP_MAX_FAILED_ATTEMPTS:
                    failure = OtpAttemptLimit("인증번호 입력 가능 횟수를 초과했습니다.")
                else:
                    failure = OtpInvalid("인증번호가 올바르지 않습니다.")

            if failure is None:
                challenge.used_at = now
                challenge.save(update_fields=["used_at"])
                user = self._create_or_refresh_mapping(identity, now)
                login(
                    request,
                    user,
                    backend="django.contrib.auth.backends.ModelBackend",
                )
                record_audit(
                    request,
                    LoginAuditLog.Event.LOGIN_SUCCESS,
                    external_user_id=identity.user_id,
                )

        if failure is not None:
            raise failure
        return user

    def create_debug_session(self, request, identity: LoginIdentity) -> LocalUserMapping:
        user = self._create_or_refresh_mapping(identity, timezone.now())
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        record_audit(
            request,
            LoginAuditLog.Event.DEBUG_LOGIN,
            external_user_id=identity.user_id,
        )
        return user

    @staticmethod
    def _create_or_refresh_mapping(identity: LoginIdentity, verified_at):
        user, _ = LocalUserMapping.objects.update_or_create(
            external_user_id=identity.user_id,
            defaults={
                "email_snapshot": identity.email,
                "is_active": True,
                "last_verified_at": verified_at,
            },
        )
        if user.has_usable_password():
            user.set_unusable_password()
            user.save(update_fields=["password"])
        return user

    @staticmethod
    def _audit_failure(request, challenge, reason):
        record_audit(
            request,
            LoginAuditLog.Event.LOGIN_FAILURE,
            external_user_id=challenge.external_user_id,
            details={"reason": reason},
        )

    @staticmethod
    def _enforce_request_limits(normalized_email, ip_hash, now):
        latest = (
            LoginOtpChallenge.objects.filter(normalized_email=normalized_email)
            .order_by("-created_at")
            .first()
        )
        if latest:
            elapsed = (now - latest.created_at).total_seconds()
            if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
                retry_after = max(1, int(settings.OTP_RESEND_COOLDOWN_SECONDS - elapsed))
                raise OtpCooldown(
                    "잠시 후 인증번호를 다시 요청해 주세요.",
                    retry_after=retry_after,
                )

        cutoff = now - timedelta(seconds=settings.OTP_RATE_LIMIT_WINDOW_SECONDS)
        email_count = LoginOtpChallenge.objects.filter(
            normalized_email=normalized_email,
            created_at__gte=cutoff,
        ).count()
        ip_count = LoginOtpChallenge.objects.filter(
            ip_hash=ip_hash,
            created_at__gte=cutoff,
        ).count()
        if (
            email_count >= settings.OTP_EMAIL_REQUEST_LIMIT
            or ip_count >= settings.OTP_IP_REQUEST_LIMIT
        ):
            raise OtpRateLimited("인증번호 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.")
