from abc import ABC, abstractmethod


class Notifier(ABC):
    @abstractmethod
    async def send(self, text: str) -> bool:
        """Send a formatted notification. Returns True on success."""

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
