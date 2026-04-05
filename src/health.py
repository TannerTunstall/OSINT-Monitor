import time
from dataclasses import dataclass, field


@dataclass
class ConnectorStatus:
    name: str
    type: str  # "source" or "notifier"
    healthy: bool = True
    last_poll: float | None = None
    last_success: float | None = None
    last_error: str | None = None
    messages_processed: int = 0
    errors: int = 0

    def record_success(self, msg_count: int = 0):
        self.healthy = True
        self.last_poll = time.time()
        self.last_success = time.time()
        self.messages_processed += msg_count
        self.last_error = None

    def record_error(self, error: str):
        self.healthy = False
        self.last_poll = time.time()
        self.last_error = error
        self.errors += 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "healthy": self.healthy,
            "last_poll": self.last_poll,
            "last_success": self.last_success,
            "last_error": self.last_error,
            "messages_processed": self.messages_processed,
            "errors": self.errors,
        }


class HealthRegistry:
    def __init__(self):
        self._connectors: dict[str, ConnectorStatus] = {}
        self.start_time = time.time()

    def register(self, name: str, connector_type: str) -> ConnectorStatus:
        status = ConnectorStatus(name=name, type=connector_type)
        self._connectors[name] = status
        return status

    def get(self, name: str) -> ConnectorStatus | None:
        return self._connectors.get(name)

    def all_statuses(self) -> list[dict]:
        return [s.to_dict() for s in self._connectors.values()]

    def summary(self) -> dict:
        statuses = list(self._connectors.values())
        return {
            "uptime_seconds": round(time.time() - self.start_time),
            "connectors_total": len(statuses),
            "connectors_healthy": sum(1 for s in statuses if s.healthy),
            "connectors": self.all_statuses(),
        }
