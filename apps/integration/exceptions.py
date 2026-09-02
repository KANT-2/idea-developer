class IntegrationError(Exception):
    """Base exception for the parent VIEW boundary."""


class IntegrationConfigurationError(IntegrationError):
    pass


class IntegrationUnavailableError(IntegrationError):
    pass


class IntegrationDataIntegrityError(IntegrationError):
    pass


class IntegrationReadOnlyError(IntegrationError):
    pass


class RoundSelectionRequired(IntegrationError):
    def __init__(self, rounds):
        self.rounds = tuple(rounds)
        super().__init__("A round must be selected.")


class NoActiveRound(IntegrationError):
    pass
