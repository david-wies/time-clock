from core.events import EventBus, Event


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
