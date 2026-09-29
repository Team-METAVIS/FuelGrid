class SimulatorError(Exception):
    """Base for all simulator integration errors."""


class SimulatorUnavailable(SimulatorError):
    """Timeouts / 5xx / injected faults after retries, or breaker open."""


class InvalidSimulatorResponse(SimulatorError):
    """Payload failed validation -> rejected + alerted."""


class AllocationRejected(SimulatorError):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message
