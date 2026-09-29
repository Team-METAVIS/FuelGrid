"""Errors every data-source adapter raises, so the rest of the system is source-agnostic."""


class SourceError(Exception):
    """Base for all data-source errors."""


class SourceUnavailable(SourceError):
    """Timeouts, 5xx, injected faults after retries, an open circuit breaker, or a feed that has gone silent."""


class InvalidSourceData(SourceError):
    """Payload failed validation: rejected and alerted, the last good state is kept."""


class AllocationRejected(SourceError):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


# Backwards-compatible names used by the simulator adapter and older tests.
SimulatorError = SourceError
SimulatorUnavailable = SourceUnavailable
InvalidSimulatorResponse = InvalidSourceData
