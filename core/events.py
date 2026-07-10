"""Simple synchronous pub/sub event bus."""

import logging
from collections.abc import Callable
from enum import Enum

logger = logging.getLogger(__name__)


class Event(Enum):
    """Identifiers for the mutation events published on the EventBus."""

    TIME_RECORDS_CHANGED = "time_records_changed"
    VACATION_CHANGED = "vacation_changed"
    SICKNESS_CHANGED = "sickness_changed"
    MILIUIM_CHANGED = "miliuim_changed"
    SETTINGS_CHANGED = "settings_changed"
    CLOCK_STATE_CHANGED = "clock_state_changed"


class EventBus:
    """Synchronous pub/sub bus: subscribers are called in-order on publish()."""

    def __init__(self, on_handler_error: Callable[[str], None] | None = None) -> None:
        self._subscribers: dict[Event, list[Callable[..., None]]] = {}
        # Optional hook the UI layer can set so a handler exception is
        # surfaced to the user, not just logged. EventBus itself stays
        # free of any tkinter dependency.
        self.on_handler_error = on_handler_error

    def subscribe(
        self, event: Event, handler: Callable[..., None]
    ) -> Callable[[], None]:
        """Registers handler for event; returns a callback that unsubscribes it."""
        self._subscribers.setdefault(event, []).append(handler)

        def _unsub() -> None:
            try:
                self._subscribers[event].remove(handler)
            except ValueError:
                pass

        return _unsub

    def publish(self, event: Event, **payload: object) -> None:
        """Calls every subscriber of event with payload, isolating their failures."""
        # Snapshot the list so an unsub inside a handler doesn't mutate
        # the iterable mid-loop.
        for handler in list(self._subscribers.get(event, [])):
            try:
                handler(**payload)
            except Exception:  # pylint: disable=broad-exception-caught
                # Subscriber callbacks are arbitrary UI/model code and may raise
                # anything; one failing handler must not stop the others or crash
                # publish(). Logged (not swallowed) and optionally surfaced below.
                message = (
                    f"EventBus: unhandled exception in handler {handler!r} "
                    f"for event {event!r}"
                )
                logger.exception(message)
                if self.on_handler_error is not None:
                    try:
                        self.on_handler_error(message)
                    except Exception:  # pylint: disable=broad-exception-caught
                        # Same rationale: the error-reporting hook is caller-supplied
                        # and must not be allowed to break the publish loop either.
                        logger.exception(
                            "EventBus: on_handler_error callback itself raised"
                        )
