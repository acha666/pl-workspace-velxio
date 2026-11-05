"""Compiling and simulating real sketches, open loop and in sessions."""

import pytest

from arduinograder import PinState, Scenario, SimulationStopped
from arduinograder.sandbox import Limits
from arduinograder.sim import Simulator
from arduinograder.toolchain import MAX_ERRORS, CompileError, Compiler
from conftest import SessionFn, SimulateFn

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

SERIAL_ECHO = """
void setup() { Serial.begin(9600); }
void loop() {
  while (Serial.available()) { Serial.print("got "); Serial.println((char)Serial.read()); }
}
"""

REACT = """
int state = 0;
void setup() { pinMode(2, INPUT); pinMode(13, OUTPUT); Serial.begin(115200); }
void loop() {
  if (state == 0 && millis() >= 300) { state = 1; digitalWrite(13, HIGH); }
  if (state == 1 && digitalRead(2) == HIGH) {
    state = 2; digitalWrite(13, LOW); Serial.println("pressed");
  }
}
"""


def test_millis_timing_is_exact_in_simulated_time(simulate: SimulateFn) -> None:
    trace = simulate(BLINK, Scenario(duration_ms=2100))
    led = trace.pin(13)
    assert [change.state for change in led.changes()] == [
        PinState.INPUT,
        PinState.LOW,
        PinState.HIGH,
        PinState.LOW,
        PinState.HIGH,
        PinState.LOW,
    ]
    edges = led.edges()
    assert edges.match([500, 1000, 1500, 2000], tolerance_ms=2)
    assert all(
        expected <= actual
        for actual, expected in zip(edges.times_ms, [500, 1000, 1500, 2000], strict=True)
    )
    assert edges.periodic(500, tolerance_ms=2)
    assert led.level(750) == 1
    assert trace.levels([13, 12], 1250) == (0, None)
    assert led.high_fraction(500, 2100) == pytest.approx(1000 / 1600, abs=0.01)
    assert trace.stop_reason == "end" and trace.end_ms == 2100


def test_inputs_follow_the_scenario_and_override_pull_ups(simulate: SimulateFn) -> None:
    scenario = (
        Scenario(duration_ms=100)
        .pulse(2, 1, at_ms=10, duration_ms=20)
        .set(3, 0, at_ms=40)
        .set(3, 1, at_ms=60)
    )
    trace = simulate(ECHO, scenario)
    assert trace.pin(2).at(5) is PinState.INPUT
    assert trace.pin(3).at(5) is PinState.INPUT_PULLUP
    assert [trace.pin(12).level(t) for t in (5, 11, 29, 31)] == [0, 1, 1, 0]
    assert [trace.pin(13).level(t) for t in (5, 41, 59, 61)] == [1, 0, 0, 1]


def test_serial_lines_are_timed_by_their_newline(simulate: SimulateFn) -> None:
    sketch = """
    unsigned long next = 100;
    void setup() { Serial.begin(9600); }
    void loop() {
      if (millis() >= next) { Serial.print("t="); Serial.println(next); next += 100; }
    }
    """
    trace = simulate(sketch, Scenario(duration_ms=350))
    lines = trace.serial.lines()
    assert [line.text for line in lines] == ["t=100", "t=200", "t=300"]
    for line, sent in zip(lines, [100, 200, 300], strict=True):
        assert sent < line.time_ms < sent + 15  # about 1 ms per byte at 9600 baud
    assert trace.serial.text() == "t=100\r\nt=200\r\nt=300\r\n"
    assert trace.serial.lines(start_ms=150)[0].text == "t=200"


def test_analog_inputs_read_back_exactly(simulate: SimulateFn) -> None:
    sketch = """
    void setup() { Serial.begin(115200); }
    void loop() { Serial.println(analogRead(A0)); delay(10); }
    """
    scenario = Scenario(duration_ms=95)
    for at_ms, value in [(0, 0), (20, 1), (40, 512), (60, 1022), (80, 1023)]:
        scenario.analog("A0", value, at_ms=at_ms)
    trace = simulate(sketch, scenario)
    readings = {round(line.time_ms, -1): int(line.text) for line in trace.serial.lines()}
    assert [readings[t] for t in (10, 30, 50, 70, 90)] == [0, 1, 512, 1022, 1023]


def test_serial_input_reaches_the_program(simulate: SimulateFn) -> None:
    trace = simulate(SERIAL_ECHO, Scenario(duration_ms=200).send("ab", at_ms=20))
    lines = trace.serial.lines()
    assert [line.text for line in lines] == ["got a", "got b"]
    assert 20 < lines[0].time_ms < lines[1].time_ms < 60


def test_a_session_reacts_to_what_the_program_does(session: SessionFn) -> None:
    with session(REACT) as run:
        lit_at = run.wait_for(13, "HIGH", timeout_ms=1000)
        assert lit_at is not None and 300 <= lit_at < 301
        assert run.state(13) is PinState.HIGH and lit_at <= run.now_ms < lit_at + 0.01
        assert run.wait_for(13, timeout_ms=100) is None
        assert run.now_ms == pytest.approx(lit_at + 100)
        assert run.pulse(2, 1, duration_ms=10)
        line = run.wait_for_line(timeout_ms=100)
        assert line is not None and line.text == "pressed" and line.time_ms > lit_at + 100
        assert run.wait_for_line(timeout_ms=10) is None
        trace = run.trace
        off = trace.pin(13).edges().falling()
        assert len(off) == 1 and lit_at + 100 <= off[0].time_ms < lit_at + 101
        assert trace.stop_reason == "end" and trace.end_ms == run.now_ms


def test_a_session_matches_the_same_scenario(simulate: SimulateFn, session: SessionFn) -> None:
    scenario = (
        Scenario(duration_ms=100)
        .pulse(2, 1, at_ms=10, duration_ms=20)
        .set(3, 0, at_ms=40)
        .release(3, at_ms=60)
    )
    expected = simulate(ECHO, scenario)
    with session(ECHO) as run:
        run.run_until(10)
        run.pulse(2, 1, duration_ms=20)
        run.run_until(40)
        run.set(3, 0)
        run.run_until(60)
        run.release(3)
        run.run_until(100)
        trace = run.trace
    assert [trace.pin(pin).changes() for pin in (12, 13)] == [
        expected.pin(pin).changes() for pin in (12, 13)
    ]
    assert trace.end_ms == expected.end_ms == 100


def test_limits_stop_the_simulation_and_explain_why(
    simulate: SimulateFn, session: SessionFn
) -> None:
    toggles = "void setup() { pinMode(13, OUTPUT); } void loop() { PINB = _BV(5); }"
    trace = simulate(toggles, Scenario(duration_ms=1000, max_pin_changes=1000))
    assert trace.stop_reason == "pin-limit" and trace.end_ms < 10
    with pytest.raises(SimulationStopped, match="reached the limit of 1000 pin changes"):
        trace.pin(13).level(500)
    with session(toggles, max_pin_changes=1000) as run:
        assert run.run_until(1000) is False
        assert run.stop_reason == "pin-limit" and not run.running
        assert run.run_for(10) is False and run.now_ms < 10

    spam = 'void setup() { Serial.begin(115200); } void loop() { Serial.println("spam"); }'
    trace = simulate(spam, Scenario(duration_ms=1000, max_serial_bytes=600))
    assert trace.stop_reason == "serial-limit"
    assert len(trace.serial) == 600


def test_same_inputs_give_the_same_trace(simulate: SimulateFn) -> None:
    scenario = Scenario(duration_ms=300).pulse(2, 1, at_ms=50, duration_ms=100)
    first, second = simulate(ECHO, scenario), simulate(ECHO, scenario)
    assert [first.pin(pin).changes() for pin in range(20)] == [
        second.pin(pin).changes() for pin in range(20)
    ]


HEAVY = """
#define A(x) x x x x x x x x x x
#define B(x) A(A(A(A(A(A(x))))))
void setup() { B(asm volatile("nop");) }
void loop() {}
"""


def test_a_runaway_compile_is_stopped_and_explained(toolchain: tuple[Compiler, Simulator]) -> None:
    compiler, _ = toolchain
    limited = Compiler(compiler.sandbox, compiler.budget, limits=Limits(cpu_s=1))
    with pytest.raises(CompileError, match="more time or memory") as error:
        limited.compile(HEAVY)
    assert "CPU time limit exceeded" in error.value.log
    assert "bug report" not in error.value.log


def test_a_released_pin_reads_its_pull_up_or_floats_low(simulate: SimulateFn) -> None:
    scenario = (
        Scenario(duration_ms=100)
        .pulse(3, 0, at_ms=10, duration_ms=20)
        .set(2, 1, at_ms=40)
        .release(2, at_ms=60)
    )
    trace = simulate(ECHO, scenario)
    assert [trace.pin(13).level(t) for t in (5, 20, 40)] == [1, 0, 1]
    assert [trace.pin(12).level(t) for t in (35, 50, 70)] == [0, 1, 0]


def test_the_compiler_stops_after_a_few_errors(toolchain: tuple[Compiler, Simulator]) -> None:
    compiler, _ = toolchain
    calls = "".join(f"  missing_{i}();\n" for i in range(100))
    with pytest.raises(CompileError) as error:
        compiler.compile(f"void setup() {{\n{calls}}}\nvoid loop() {{}}\n")
    assert error.value.log.count("was not declared") == MAX_ERRORS
    assert f"-fmax-errors={MAX_ERRORS}" in error.value.log


GREETS = """
void setup() { pinMode(2, INPUT); Serial.begin(115200); Serial.print("re"); }
void loop() {
  if (millis() == 20) { Serial.println("ady"); }
  if (digitalRead(2) == HIGH) { Serial.println("pressed"); while (digitalRead(2) == HIGH) {} }
}
"""

TOGETHER = (
    "void setup() { DDRB = 0b00100010; } void loop() { if (millis() >= 10) PORTB = 0b00100010; }"
)


def test_waits_hand_out_what_happened_since_the_latest_input(session: SessionFn) -> None:
    with session(REACT) as run:
        run.run_until(400)
        lit_at = run.wait_for(13, "HIGH", timeout_ms=0)
        assert lit_at is not None and 300 <= lit_at < 301 and run.now_ms == 400
        assert run.wait_for(13, "HIGH", timeout_ms=0) is None
        run.pulse(2, 1, duration_ms=10)
        off_at = run.wait_for(13, "LOW", timeout_ms=100)
        assert off_at is not None and 400 <= off_at < 401 and run.now_ms == 410
        line = run.wait_for_line(timeout_ms=0)
        assert line is not None and line.text == "pressed"


def test_an_input_starts_the_waits_afresh_but_keeps_a_line_in_progress(
    session: SessionFn,
) -> None:
    with session(GREETS) as run:
        run.run_until(50)
        run.pulse(2, 1, duration_ms=10)
        line = run.wait_for_line(timeout_ms=50)
        assert line is not None and line.text == "pressed", "'ready' is not a reply to the press"
    with session(GREETS) as run:
        run.run_until(10)
        run.set(3, 1)
        line = run.wait_for_line(timeout_ms=50)
        assert line is not None and line.text == "ready" and 20 <= line.time_ms < 21


def test_each_pin_keeps_its_own_place_in_the_records(session: SessionFn) -> None:
    with session(TOGETHER) as run:
        high_13 = run.wait_for(13, "HIGH", timeout_ms=100)
        high_9 = run.wait_for(9, "HIGH", timeout_ms=0)
        assert high_13 is not None and high_13 == high_9
        assert run.wait_for(9, timeout_ms=0) is None


NO_NEWLINE = """
void setup() { Serial.begin(115200); }
void loop() { Serial.print("value "); }
"""


def test_each_compilation_keeps_its_own_firmware(toolchain: tuple[Compiler, Simulator]) -> None:
    compiler, simulator = toolchain
    blink = compiler.compile(BLINK)
    quiet = compiler.compile("void setup() {}\nvoid loop() {}\n")
    assert blink.path != quiet.path
    assert simulator.run(blink, Scenario(duration_ms=1200)).pin(13).edges()
    assert not simulator.run(quiet, Scenario(duration_ms=1200)).pin(13).edges()


def test_a_timed_out_wait_leaves_the_changes_for_a_later_one(session: SessionFn) -> None:
    with session(BLINK) as run:
        run.run_until(100)
        assert run.wait_for(13, "INPUT", timeout_ms=600) is None
        assert run.wait_for(13, "HIGH", timeout_ms=0) == pytest.approx(500, abs=1)


def test_waiting_for_a_line_needs_a_newline(session: SessionFn) -> None:
    with session(NO_NEWLINE) as run:
        assert run.wait_for_line(timeout_ms=200) is None
        assert run.now_ms == 200
        assert run.trace.serial.text().startswith("value value")
