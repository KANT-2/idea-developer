class AiInfrastructureError(Exception):
    pass


class AiPromptNotConfigured(AiInfrastructureError):
    pass


class AiUsageLimitExceeded(AiInfrastructureError):
    pass


class AiOutputValidationError(AiInfrastructureError):
    pass


class AiReferenceValidationError(AiOutputValidationError):
    pass


class AiProviderError(AiInfrastructureError):
    def __init__(self, message, *, code="provider_error", retryable=True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class AiProviderTimeout(AiProviderError):
    def __init__(self, message="AI provider timed out."):
        super().__init__(message, code="timeout", retryable=True)


class AiJobNotCancellable(AiInfrastructureError):
    pass


class AiJobNotRetryable(AiInfrastructureError):
    pass
