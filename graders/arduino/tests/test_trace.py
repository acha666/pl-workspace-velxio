"""Trace queries on recorded replies, without the toolchain."""

from collections.abc import Callable

import pytest

from arduinograder import PinState, Scenario, SimulationStopped, Trace
from arduinograder.sim import AnalogEvent, DigitalEvent, ReleaseEvent, SendEvent, runner
from arduinograder.sim.trace import as_stop_reason

BLINK_TRACE = """
P 0 13 I
P 16000 13 L
P 32000 13 H
P 8000000 13 L
P 16000000 13 H
P 24000000 13 I
P 24400000 13 L
S 1600000 104
S 1616000 105
S 1632000 10
S 1700000 33
T 32000000 reached
"""


@pytest.fixture
def trace() -> Trace:
    return Trace.from_text(BLINK_TRACE, max_pin_changes=99, max_serial_bytes=9)


def test_pin_states_and_levels(trace: Trace) -> None:
    led = trace.pin(13)
    assert [led.at(ms) for ms in (0, 1.5, 3, 1200, 1510)] == [
        PinState.INPUT,
        PinState.LOW,
        PinState.HIGH,
        PinState.HIGH,
        PinState.INPUT,
    ]
    assert led.at(3).is_high and led.at(3).is_output and not led.at(0).is_output
    assert led.level(3) == 1 and led.level(1.5) == 0 and led.level(1505) is None
    assert trace.levels([13, 12, "A0"], 3) == (1, None, None)
    assert trace.pin("A0").at(100) is PinState.INPUT
    assert str(PinState.INPUT_PULLUP) == "INPUT_PULLUP"


def test_changes_and_edges(trace: Trace) -> None:
    led = trace.pin(13)
    assert [change.state for change in led.changes(end_ms=10)] == [
        PinState.INPUT,
        PinState.LOW,
        PinState.HIGH,
    ]
    # Mode changes are not edges; HIGH, released, then LOW is one falling edge.
    assert led.edges().times_ms == [2, 500, 1000, 1525]
    assert led.edges(start_ms=100).times_ms == [500, 1000, 1525]
    assert led.edges(start_ms=100, end_ms=1200).rising().times_ms == [1000]
    assert led.edges().falling().times_ms == [500, 1525]
    assert led.edges(start_ms=100).match([500, 1000, 1525], tolerance_ms=1)
    assert not led.edges(start_ms=100).match([500, 1000], tolerance_ms=1)
    assert led.edges(start_ms=100, end_ms=1200).periodic(500, tolerance_ms=1)
    assert not led.edges(start_ms=100).periodic(500, tolerance_ms=1)
    assert led.edges(start_ms=100).intervals_ms() == [500, 525]
    assert led.edges(start_ms=100).describe() == "500 ms, 1000 ms, 1525 ms"
    assert led.edges(start_ms=1600).describe() == "never"


def test_high_fraction_and_stability(trace: Trace) -> None:
    led = trace.pin(13)
    assert led.high_fraction(0, 2000) == pytest.approx((498 + 500) / 2000)
    assert led.high_fraction(100, 400) == 1.0
    assert led.high_fraction(600, 900) == 0.0
    assert led.stable(600, 900) and not led.stable(400, 600)
    with pytest.raises(ValueError):
        led.high_fraction(500, 500)


def test_serial_text_and_lines(trace: Trace) -> None:
    assert trace.serial.text() == "hi\n!"
    assert trace.serial.lines() == [(102, "hi"), (106.25, "!")]
    assert trace.serial.lines(start_ms=103) == [(106.25, "!")]
    assert trace.serial.bytes(end_ms=100.5) == b"h"
    assert len(trace.serial) == 4 and trace.serial


def test_times_past_the_end_are_errors_or_stops(trace: Trace) -> None:
    assert trace.end_ms == 2000 and not trace.ended_early and trace.stop_message is None
    with pytest.raises(ValueError, match="after the simulation ends"):
        trace.pin(13).at(2001)
    crashed = Trace.from_text("P 0 13 I\nT 160000 crashed")
    assert crashed.ended_early and crashed.stop_reason == "crashed"
    with pytest.raises(SimulationStopped, match="crashed at 10 ms"):
        crashed.pin(13).level(11)
    limited = Trace.from_text("T 16000 pin-limit", max_pin_changes=5)
    assert limited.stop_message is not None and "5 times, the limit" in limited.stop_message
    with pytest.raises(ValueError):
        Trace.from_text("P 0 13 I")
    with pytest.raises(ValueError):
        Trace.from_text("T 16000 vanished")


def test_scenarios_order_events_and_reject_invalid_inputs() -> None:
    scenario = (
        Scenario(duration_ms=100)
        .pulse(2, 1, at_ms=10, duration_ms=20)
        .set("A0", 1, at_ms=5)
        .send("hi\n", at_ms=50)
        .analog("A1", 512)
    )
    assert scenario.events == [
        AnalogEvent(0, 4, 1, 512),
        DigitalEvent(80000, 2, 14, 1),
        DigitalEvent(160000, 0, 2, 1),
        ReleaseEvent(480000, 1, 2),
        SendEvent(800000, 3, b"hi\n"),
    ]
    assert Scenario(duration_ms=100).pulse(2, 0, at_ms=10, duration_ms=20).events == [
        DigitalEvent(160000, 0, 2, 0),
        ReleaseEvent(480000, 1, 2),
    ]
    same = Scenario(duration_ms=100).pulse(2, 1, at_ms=10, duration_ms=20).set("A0", 1, at_ms=5)
    same.send("hi\n", at_ms=50).analog("A1", 512)
    assert scenario.key == same.key
    assert scenario.key != Scenario(duration_ms=100).key
    calls: list[Callable[[], object]] = [
        lambda: scenario.set(20, 1),
        lambda: scenario.set("A6", 1),
        lambda: scenario.set(True, 1),
        lambda: scenario.set(2, 1, at_ms=101),
        lambda: scenario.set(2, 1, at_ms=-1),
        lambda: scenario.analog(2, 100),
        lambda: scenario.analog("A0", 1024),
    ]
    for call in calls:
        with pytest.raises(ValueError):
            call()
    with pytest.raises(ValueError):
        Scenario(duration_ms=0)


def test_reason_words_match_the_avrsim_protocol() -> None:
    for reason in ("reached", "watched", "done", "crashed", "pin-limit", "serial-limit"):
        assert runner._as_run_reason(reason) == reason
    assert {"done", "crashed", "pin-limit", "serial-limit"} == runner.FINAL_REASONS
    with pytest.raises(RuntimeError):
        runner._as_run_reason("vanished")
    assert as_stop_reason("reached") == "end"
    assert as_stop_reason("pin-limit") == "pin-limit"
