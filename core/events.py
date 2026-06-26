from enum import Enum, auto
from typing import Callable, Any

class Event(Enum):
    TIME_RECORDS_CHANGED = auto()
    VACATION_CHANGED = auto()
    SICKNESS_CHANGED = auto()
    SETTINGS_CHANGED = auto()
    CLOCK_STATE_CHANGED = auto()

class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[Event, list[Callable[..., Any]]] = {
            event: [] for event in Event
        }

    def subscribe(self, event: Event, handler: Callable[..., Any]) -> Callable[[], None]:
        if handler not in self._listeners[event]:
            self._listeners[event].append(handler)
        
        def unsubscribe() -> None:
            if handler in self._listeners[event]:
                self._listeners[event].remove(handler)
        
        return unsubscribe

    def publish(self, event: Event, **payload: Any) -> None:
        # Create a shallow copy of the listeners list to prevent issues if a listener unsubscribes during callback execution
        for handler in list(self._listeners[event]):
            handler(**payload)
