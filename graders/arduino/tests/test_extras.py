import subprocess
import sys

import pytest

from arduinograder import Scenario, StopGrading
from arduinograder.extras import Segment as S
from arduinograder.extras import SevenSegment, find_calls, forbid_calls, no_calls
from conftest import SimulateFn

COUNTER = """
const int SEG_PINS[7] = {2, 3, 4, 5, 6, 7, 8};
const byte DIGIT_SEGMENTS[10][7] = {
  {1,1,1,1,1,1,0}, {0,1,1,0,0,0,0}, {1,1,0,1,1,0,1}, {1,1,1,1,0,0,1}, {0,1,1,0,0,1,1},
  {1,0,1,1,0,1,1}, {1,0,1,1,1,1,1}, {1,1,1,0,0,0,0}, {1,1,1,1,1,1,1}, {1,1,1,1,0,1,1},
};
int digit = 0, last = LOW;
const int DP_PIN = 9;
void show(int d) {
  for (int i = 0; i < 7; i++) digitalWrite(SEG_PINS[i], DIGIT_SEGMENTS[d][i]);
  digitalWrite(DP_PIN, d % 2);
}
void setup() {
  for (int i = 0; i < 7; i++) pinMode(SEG_PINS[i], OUTPUT);
  pinMode(DP_PIN, OUTPUT);
  pinMode(11, INPUT);
  show(0);
}
void loop() {
  int now = digitalRead(11);
  if (now == HIGH && last == LOW) { digit = (digit + 1) % 10; show(digit); }
  last = now;
}
"""


def test_core_package_does_not_load_the_extras() -> None:
    check = (
        "import sys, arduinograder; "
        "assert not {'arduinograder.extras', 'tree_sitter'} & set(sys.modules)"
    )
    subprocess.run([sys.executable, "-c", check], check=True)


def test_find_calls_ignores_comments_strings_and_other_names() -> None:
    source = (
        "void loop() {\n"
        "  // delay(100) in a comment\n"
        '  Serial.println("delay(100) in a string");\n'
        "  delay (5);\n"
        "  ::delay(2);\n"
        "  mydelay(3); _delay_ms(4); delayMicroseconds(1);\n"
        "}\n"
    )
    calls = find_calls(source, "delay")
    assert [(call.name, call.line, call.text) for call in calls] == [
        ("delay", 4, "delay (5);"),
        ("delay", 5, "::delay(2);"),
    ]
    assert [call.line for call in find_calls(source, "delayMicroseconds")] == [6]


def test_find_calls_line_numbers_survive_unusual_line_breaks() -> None:
    source = "int a; /* \x0c form feed */\r\nvoid loop() {\r\n  delay(1);\r\n}\r\n"
    assert [call.line for call in find_calls(source, "delay")] == [3]


def test_forbid_calls_stops_grading_and_lists_the_calls() -> None:
    source = "void loop() {\n  delay(5);\n  delayMicroseconds(1);\n}\n"
    with pytest.raises(StopGrading) as stopped:
        forbid_calls(source, "delay", "delayMicroseconds")
    assert str(stopped.value) == (
        "Your sketch calls delay(), delayMicroseconds(), which this question does "
        "not allow:\n    line 2: delay(5);\n    line 3: delayMicroseconds(1);"
    )
    forbid_calls(source, "tone")


def test_no_calls_is_a_gate_on_the_source() -> None:
    gate = no_calls("delay")
    assert gate("void loop() {}") is None
    with pytest.raises(StopGrading, match="calls delay\\(\\)"):
        gate("void loop() { delay(1); }")


def test_seven_segment_gives_lit_segments_from_the_trace(simulate: SimulateFn) -> None:
    scenario = Scenario(duration_ms=400)
    for at_ms in (100, 200, 300):
        scenario.pulse(11, 1, at_ms=at_ms, duration_ms=20)
    trace = simulate(COUNTER, scenario)
    display = SevenSegment([2, 3, 4, 5, 6, 7, 8, 9])
    assert [display.segments(trace, at_ms=t) for t in (50, 150, 250, 350)] == [
        S.A | S.B | S.C | S.D | S.E | S.F,
        S.B | S.C | S.DP,
        S.A | S.B | S.D | S.E | S.G,
        S.A | S.B | S.C | S.D | S.G | S.DP,
    ]
    without_dp = SevenSegment([2, 3, 4, 5, 6, 7, 8, None])
    assert without_dp.segments(trace, at_ms=150) == S.B | S.C
    anode = SevenSegment([2, 3, 4, 5, 6, 7, 8, 9], common="anode")
    assert anode.segments(trace, at_ms=150) == S.A | S.D | S.E | S.F | S.G
    unwired = SevenSegment([10, 12, 13, 14, 15, 16, 17, 18])
    assert unwired.segments(trace, at_ms=150) == S(0)
    with pytest.raises(ValueError):
        SevenSegment([2, 3, 4, 5, 6, 7, 8])


def test_segments_match_arduino_digit_bytes_and_read_for_students() -> None:
    assert S(0x3F) == S.A | S.B | S.C | S.D | S.E | S.F
    assert S(0x86) == S.B | S.C | S.DP
    assert (S(0x86) & ~S.DP) == S.B | S.C
    assert f"{S.B | S.C | S.DP}" == "B, C, DP"
    assert f"{S(0)}" == "none"
