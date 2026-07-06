import logging
from typing import Callable

import pytest

from core.events import Event, EventBus


def test_subscribe_and_publish() -> None:
    bus = EventBus()
    calls: list[int] = []
    bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda: calls.append(1))
    bus.publish(Event.TIME_RECORDS_CHANGED)
    assert calls == [1]


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    calls: list[int] = []
    unsub = bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda: calls.append(1))
    bus.publish(Event.TIME_RECORDS_CHANGED)
    assert calls == [1]
    unsub()
    bus.publish(Event.TIME_RECORDS_CHANGED)
    assert calls == [1]  # no second delivery after unsubscribe


def test_multiple_subscribers_same_event() -> None:
    bus = EventBus()
    a: list[int] = []
    b: list[int] = []
    bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda: a.append(1))
    bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda: b.append(2))
    bus.publish(Event.TIME_RECORDS_CHANGED)
    assert a == [1]
    assert b == [2]


def test_unsubscribe_only_removes_target_handler() -> None:
    bus = EventBus()
    a: list[int] = []
    b: list[int] = []
    unsub_a = bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda: a.append(1))
    bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda: b.append(2))
    bus.publish(Event.TIME_RECORDS_CHANGED)
    assert a == [1] and b == [2]
    unsub_a()
    bus.publish(Event.TIME_RECORDS_CHANGED)
    assert a == [1]  # handler A not called again
    assert b == [2, 2]  # handler B still fires


def test_double_unsubscribe_is_safe() -> None:
    bus = EventBus()
    calls: list[int] = []
    unsub = bus.subscribe(Event.TIME_RECORDS_CHANGED, lambda: calls.append(1))
    unsub()
    unsub()  # second call must not raise
    bus.publish(Event.TIME_RECORDS_CHANGED)
    assert calls == []


def test_publish_unknown_event_is_silent() -> None:
    bus = EventBus()
    # Publishing an event with no subscribers must not raise
    bus.publish(Event.VACATION_CHANGED)


# ─────────────── Handler-exception handling ──────────────────────────────────


def test_handler_exception_is_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()

    def bad_handler() -> None:
        raise ValueError("boom")

    bus.subscribe(Event.TIME_RECORDS_CHANGED, bad_handler)
    with caplog.at_level(logging.ERROR, logger="core.events"):
        bus.publish(Event.TIME_RECORDS_CHANGED)  # must not propagate

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert "bad_handler" in record.message
    assert "TIME_RECORDS_CHANGED" in record.message
    assert record.exc_info is not None


def test_handler_exception_does_not_stop_later_handlers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    calls: list[str] = []

    def bad_handler() -> None:
        raise RuntimeError("boom")

    def good_handler() -> None:
        calls.append("good")

    bus.subscribe(Event.TIME_RECORDS_CHANGED, bad_handler)
    bus.subscribe(Event.TIME_RECORDS_CHANGED, good_handler)
    with caplog.at_level(logging.ERROR, logger="core.events"):
        bus.publish(Event.TIME_RECORDS_CHANGED)

    assert calls == ["good"]


def test_handler_exception_invokes_on_handler_error_callback() -> None:
    received: list[str] = []
    bus = EventBus(on_handler_error=received.append)

    def bad_handler() -> None:
        raise ValueError("boom")

    bus.subscribe(Event.TIME_RECORDS_CHANGED, bad_handler)
    bus.publish(Event.TIME_RECORDS_CHANGED)

    assert len(received) == 1
    assert "bad_handler" in received[0]


def test_no_on_handler_error_callback_is_fine(caplog: pytest.LogCaptureFixture) -> None:
    bus = EventBus()  # no callback supplied

    def bad_handler() -> None:
        raise ValueError("boom")

    bus.subscribe(Event.TIME_RECORDS_CHANGED, bad_handler)
    with caplog.at_level(logging.ERROR, logger="core.events"):
        bus.publish(Event.TIME_RECORDS_CHANGED)  # must not raise


def test_unsubscribe_during_publish_uses_snapshot() -> None:
    # publish() snapshots the subscriber list before iterating, so a handler
    # that unsubscribes itself (or another handler) mid-publish must not
    # raise and must not affect delivery for the in-progress publish() call.
    bus = EventBus()
    calls: list[str] = []
    unsub_self: Callable[[], None] | None = None

    def self_unsubscribing_handler() -> None:
        calls.append("self")
        assert unsub_self is not None
        unsub_self()  # unsubscribe from inside the handler

    def other_handler() -> None:
        calls.append("other")

    unsub_self = bus.subscribe(Event.TIME_RECORDS_CHANGED, self_unsubscribing_handler)
    bus.subscribe(Event.TIME_RECORDS_CHANGED, other_handler)

    bus.publish(Event.TIME_RECORDS_CHANGED)  # must not raise
    # Both handlers were subscribed when the snapshot was taken, so both
    # still fire during this publish() call.
    assert calls == ["self", "other"]

    calls.clear()
    bus.publish(Event.TIME_RECORDS_CHANGED)
    # The self-unsubscribed handler is gone; only "other" fires now.
    assert calls == ["other"]


def test_on_handler_error_callback_raising_does_not_propagate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A bad subscriber handler must never be able to take down the caller of
    # publish() -- not even indirectly via a broken on_handler_error callback
    # (e.g. a UI error dialog invoked while the window is mid-teardown).
    def broken_callback(message: str) -> None:
        raise RuntimeError("callback boom")

    bus = EventBus(on_handler_error=broken_callback)

    def bad_handler() -> None:
        raise ValueError("boom")

    bus.subscribe(Event.TIME_RECORDS_CHANGED, bad_handler)
    with caplog.at_level(logging.ERROR, logger="core.events"):
        bus.publish(Event.TIME_RECORDS_CHANGED)  # must not propagate

    assert len(caplog.records) == 2
    handler_record, callback_record = caplog.records
    assert "bad_handler" in handler_record.message
    assert handler_record.exc_info is not None

    assert "on_handler_error callback itself raised" in callback_record.message
    assert callback_record.exc_info is not None
