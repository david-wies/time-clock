"""Simple synchronous pub/sub event bus."""
import sys
import traceback
from enum import Enum
from typing import Callable


class Event(Enum):
    TIME_RECORDS_CHANGED = "time_records_changed"
    VACATION_CHANGED = "vacation_changed"
    SICKNESS_CHANGED = "sickness_changed"
    MILIUIM_CHANGED = "miliuim_changed"
    SETTINGS_CHANGED = "settings_changed"
    CLOCK_STATE_CHANGED = "clock_state_changed"


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[Event, list[Callable[..., None]]] = {}

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
                print(
                    f"EventBus: unhandled exception in handler {handler!r} "
                    f"for event {event!r}:",
                    file=sys.stderr,
                )
                traceback.print_exc(file=sys.stderr)
