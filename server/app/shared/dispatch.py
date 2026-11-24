"""Message type → handler registry, shared by the WS gateway and the worker IPC.

New message types register a handler; the read loops never change (open/closed).
"""

from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

Ctx = TypeVar("Ctx")
Handler = Callable[[Ctx, Any], Awaitable[Any]]


class UnknownMessage(LookupError):
    def __init__(self, message_type: str) -> None:
        super().__init__(message_type)
        self.message_type = message_type


class Dispatcher(Generic[Ctx]):
    def __init__(self) -> None:
        self._handlers: dict[str, Handler[Ctx]] = {}

    def add(self, message_type: str, handler: Handler[Ctx]) -> None:
        if message_type in self._handlers:
            raise ValueError(f"handler for {message_type!r} already registered")
        self._handlers[message_type] = handler

    def on(self, message_type: str) -> Callable[[Handler[Ctx]], Handler[Ctx]]:
        """Decorator form of `add`."""

        def register(handler: Handler[Ctx]) -> Handler[Ctx]:
            self.add(message_type, handler)
            return handler

        return register

    def handles(self, message_type: str) -> bool:
        return message_type in self._handlers

    async def dispatch(self, message_type: str, ctx: Ctx, payload: Any) -> Any:
        handler = self._handlers.get(message_type)
        if handler is None:
            raise UnknownMessage(message_type)
        return await handler(ctx, payload)
