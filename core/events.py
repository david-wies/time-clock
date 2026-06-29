"""Simple synchronous pub/sub event bus."""
from enum import Enum
from typing import Callable


class Event(Enum):
    TIME_RECORDS_CHANGED = "time_records_changed"
    VACATION_CHANGED = "vacation_changed"
    SICKNESS_CHANGED = "sickness_changed"
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
        for handler in self._subscribers.get(event, []):
            handler(**payload)
