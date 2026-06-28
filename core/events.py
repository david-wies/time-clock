"""Simple synchronous pub/sub event bus."""
from enum import Enum
from typing import Callable, Dict, List


class Event(Enum):
    TIME_RECORDS_CHANGED = "time_records_changed"
    VACATION_CHANGED = "vacation_changed"
    SICKNESS_CHANGED = "sickness_changed"
    SETTINGS_CHANGED = "settings_changed"
    CLOCK_STATE_CHANGED = "clock_state_changed"


class EventBus:
    def __init__(self):
        self._subscribers: Dict[Event, List[Callable]] = {}
        return

    def subscribe(self, event: Event, handler: Callable) -> None:
        self._subscribers.setdefault(event, []).append(handler)
        return
    
    def unsubscribe(self, event: Event, handler: Callable) -> None:
        if event in self._subscribers:
            self._subscribers[event].remove(handler)
        return

    def publish(self, event: Event, **payload) -> None:
        for handler in self._subscribers.get(event, []):
            handler(**payload)
        return
