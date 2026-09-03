class AuthenticationFlowError(Exception):
    code = "authentication_error"
    status = 400

    def __init__(self, message, *, retry_after=None):
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


class InvalidEmail(AuthenticationFlowError):
    code = "invalid_email"


class OtpCooldown(AuthenticationFlowError):
    code = "resend_cooldown"
    status = 429


class OtpRateLimited(AuthenticationFlowError):
    code = "rate_limited"
    status = 429


class OtpInvalid(AuthenticationFlowError):
    code = "invalid_code"


class OtpExpired(AuthenticationFlowError):
    code = "code_expired"
    status = 410


class OtpAlreadyUsed(AuthenticationFlowError):
    code = "code_already_used"
    status = 409


class OtpAttemptLimit(AuthenticationFlowError):
    code = "attempt_limit"
    status = 429


class OtpDeliveryUnavailable(AuthenticationFlowError):
    code = "delivery_unavailable"
    status = 503
