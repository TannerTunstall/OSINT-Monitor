from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Message:
    """Normalized message from any source."""
    source: str        # e.g. "telegram", "twitter", "aws_health"
    source_id: str     # unique ID within the source
    author: str | None
    content: str
    url: str | None = None
    timestamp: datetime | None = None


class Source(ABC):
    @abstractmethod
    async def start(self) -> None:
        """Initialize the source (connect, authenticate, etc.)."""

    @abstractmethod
    async def poll(self) -> list[Message]:
        """Fetch new messages. Called periodically or used for initial backfill."""

    @abstractmethod
    async def stop(self) -> None:
        """Clean up resources."""
