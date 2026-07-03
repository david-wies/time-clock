"""Simple synchronous pub/sub event bus."""
import logging
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class Event(Enum):
    TIME_RECORDS_CHANGED = "time_records_changed"
    VACATION_CHANGED = "vacation_changed"
    SICKNESS_CHANGED = "sickness_changed"
    MILIUIM_CHANGED = "miliuim_changed"
    SETTINGS_CHANGED = "settings_changed"
    CLOCK_STATE_CHANGED = "clock_state_changed"


class EventBus:
    def __init__(self, on_handler_error: Optional[Callable[[str], None]] = None) -> None:
        self._subscribers: dict[Event, list[Callable[..., None]]] = {}
        # Optional hook the UI layer can set so a handler exception is
        # surfaced to the user, not just logged. EventBus itself stays
        # free of any tkinter dependency.
        self.on_handler_error = on_handler_error

    def subscribe(self, event: Event, handler: Callable[..., None]) -> Callable[[], None]:
        self._subscribers.setdefault(event, []).append(handler)

        def _unsub() -> None:
            try:
                self._subscribers[event].remove(handler)
            except ValueError:
                pass
        return _unsub

    def publish(self, event: Event, **payload: object) -> None:
        # Snapshot the list so an unsub inside a handler doesn't mutate
        # the iterable mid-loop.
        for handler in list(self._subscribers.get(event, [])):
            try:
                handler(**payload)
            except Exception:
                message = (
                    f"EventBus: unhandled exception in handler {handler!r} "
                    f"for event {event!r}"
                )
                logger.exception(message)
                if self.on_handler_error is not None:
                    try:
                        self.on_handler_error(message)
                    except Exception:
                        logger.exception(
                            "EventBus: on_handler_error callback itself raised"
                        )
