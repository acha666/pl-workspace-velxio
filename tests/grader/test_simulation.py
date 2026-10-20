import pytest

from arduinograder import Scenario, SimulationStopped

BLINK = """
unsigned long last = 0;
bool on = false;
void setup() { pinMode(13, OUTPUT); }
void loop() {
  if (millis() - last >= 500) { last += 500; on = !on; digitalWrite(13, on); }
}
"""

ECHO = """
void setup() {
  pinMode(2, INPUT); pinMode(3, INPUT_PULLUP);
  pinMode(12, OUTPUT); pinMode(13, OUTPUT);
}
void loop() { digitalWrite(12, digitalRead(2)); digitalWrite(13, digitalRead(3)); }
"""


def test_millis_timing_is_exact_in_simulated_time(simulate):
    trace = simulate(BLINK, Scenario(duration_ms=2100))
    changes = trace.changes(13)
    assert [state for _, state in changes] == [
        "INPUT",
        "LOW",
        "HIGH",
        "LOW",
        "HIGH",
        "LOW",
    ]
    for (time, _), expected in zip(changes[2:], [500, 1000, 1500, 2000]):
        assert expected <= time < expected + 2
    assert trace.level(13, at_ms=750) == 1
    assert trace.levels([13, 12], at_ms=1250) == (0, None)
    assert trace.stop_reason == "end" and trace.end_ms == 2100


def test_inputs_follow_the_scenario_and_override_pull_ups(simulate):
    scenario = (
        Scenario(duration_ms=100)
        .press(2, at_ms=10, hold_ms=20)
        .set(3, 0, at_ms=40)
        .set(3, 1, at_ms=60)
    )
    trace = simulate(ECHO, scenario)
    assert trace.state(2, at_ms=5) == "INPUT"
    assert trace.state(3, at_ms=5) == "INPUT_PULLUP"
    assert [trace.level(12, at_ms=t) for t in (5, 11, 29, 31)] == [0, 1, 1, 0]
    assert [trace.level(13, at_ms=t) for t in (5, 41, 59, 61)] == [1, 0, 0, 1]


def test_serial_lines_are_timed_by_their_newline(simulate):
    sketch = """
    unsigned long next = 100;
    void setup() { Serial.begin(9600); }
    void loop() {
      if (millis() >= next) { Serial.print("t="); Serial.println(next); next += 100; }
    }
    """
    trace = simulate(sketch, Scenario(duration_ms=350))
    lines = trace.serial_lines()
    assert [text for _, text in lines] == ["t=100", "t=200", "t=300"]
    for (time, _), sent in zip(lines, [100, 200, 300]):
        assert sent < time < sent + 15  # about 1 ms per byte at 9600 baud
    assert trace.serial_text() == "t=100\r\nt=200\r\nt=300\r\n"


def test_analog_inputs_read_back_exactly(simulate):
    sketch = """
    void setup() { Serial.begin(115200); }
    void loop() { Serial.println(analogRead(A0)); delay(10); }
    """
    scenario = Scenario(duration_ms=95)
    for at_ms, value in [(0, 0), (20, 1), (40, 512), (60, 1022), (80, 1023)]:
        scenario.analog("A0", value, at_ms=at_ms)
    trace = simulate(sketch, scenario)
    readings = {round(time, -1): int(text) for time, text in trace.serial_lines()}
    assert [readings[t] for t in (10, 30, 50, 70, 90)] == [0, 1, 512, 1022, 1023]


def test_limits_stop_the_simulation_and_explain_why(simulate):
    toggles = "void setup() { pinMode(13, OUTPUT); } void loop() { PINB = _BV(5); }"
    trace = simulate(toggles, Scenario(duration_ms=1000, max_pin_changes=1000))
    assert trace.stop_reason == "pin-limit" and trace.end_ms < 10
    with pytest.raises(
        SimulationStopped, match="changed its pins more than 1000 times"
    ):
        trace.level(13, at_ms=500)

    spam = (
        'void setup() { Serial.begin(115200); } void loop() { Serial.println("spam"); }'
    )
    trace = simulate(spam, Scenario(duration_ms=1000, max_serial_bytes=600))
    assert trace.stop_reason == "serial-limit"
    assert len(trace.serial_text()) == 600


def test_same_inputs_give_the_same_trace(simulate):
    scenario = Scenario(duration_ms=300).press(2, at_ms=50, hold_ms=100)
    first, second = simulate(ECHO, scenario), simulate(ECHO, scenario)
    assert [first.changes(pin) for pin in range(20)] == [
        second.changes(pin) for pin in range(20)
    ]


def test_scenarios_reject_invalid_inputs():
    scenario = Scenario(duration_ms=100)
    for call in [
        lambda: scenario.set(20, 1),
        lambda: scenario.set("A6", 1),
        lambda: scenario.set(True, 1),
        lambda: scenario.set(2, 1, at_ms=101),
        lambda: scenario.set(2, 1, at_ms=-1),
        lambda: scenario.analog(2, 100),
        lambda: scenario.analog("A0", 1024),
    ]:
        with pytest.raises(ValueError):
            call()
    with pytest.raises(ValueError):
        Scenario(duration_ms=0)
