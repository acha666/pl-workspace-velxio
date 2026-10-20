from arduinograder import DIGITS, Scenario, SevenSegment, find_calls

COUNTER = """
const int SEG_PINS[7] = {2, 3, 4, 5, 6, 7, 8};
const byte DIGIT_SEGMENTS[10][7] = {
  {1,1,1,1,1,1,0}, {0,1,1,0,0,0,0}, {1,1,0,1,1,0,1}, {1,1,1,1,0,0,1}, {0,1,1,0,0,1,1},
  {1,0,1,1,0,1,1}, {1,0,1,1,1,1,1}, {1,1,1,0,0,0,0}, {1,1,1,1,1,1,1}, {1,1,1,1,0,1,1},
};
int digit = 0, last = LOW;
void show(int d) {
  for (int i = 0; i < 7; i++) digitalWrite(SEG_PINS[i], DIGIT_SEGMENTS[d][i]);
}
void setup() {
  for (int i = 0; i < 7; i++) pinMode(SEG_PINS[i], OUTPUT);
  pinMode(11, INPUT);
  show(0);
}
void loop() {
  int now = digitalRead(11);
  if (now == HIGH && last == LOW) { digit = (digit + 1) % 10; show(digit); }
  last = now;
}
"""


def test_find_calls_ignores_comments_strings_and_other_names():
    source = (
        "void loop() {\n"
        "  // delay(100) in a comment\n"
        '  Serial.println("delay(100) in a string");\n'
        "  delay (5);\n"
        "  ::delay(2);\n"
        "  mydelay(3); _delay_ms(4); delayMicroseconds(1);\n"
        "}\n"
    )
    calls = find_calls(source, ["delay"])
    assert [(call.name, call.line, call.text) for call in calls] == [
        ("delay", 4, "delay (5);"),
        ("delay", 5, "::delay(2);"),
    ]
    assert [call.line for call in find_calls(source, ["delayMicroseconds"])] == [6]


def test_find_calls_line_numbers_survive_unusual_line_breaks():
    source = "int a; /* \x0c form feed */\r\nvoid loop() {\r\n  delay(1);\r\n}\r\n"
    assert [call.line for call in find_calls(source, ["delay"])] == [3]


def test_seven_segment_reads_digits_from_the_trace(simulate):
    scenario = Scenario(duration_ms=400)
    for at_ms in (100, 200, 300):
        scenario.press(11, at_ms=at_ms, hold_ms=20)
    trace = simulate(COUNTER, scenario)
    display = SevenSegment([2, 3, 4, 5, 6, 7, 8])
    assert [display.read(trace, at_ms=t) for t in (50, 150, 250, 350)] == list("0123")
    assert display.segments(trace, at_ms=150) == "bc"
    anode = SevenSegment([2, 3, 4, 5, 6, 7, 8], common="anode")
    assert anode.segments(trace, at_ms=150) == "adefg"
    assert anode.read(trace, at_ms=150) is None


def test_seven_segment_fonts_accept_alternatives(simulate):
    trace = simulate(COUNTER, Scenario(duration_ms=50))
    font = {**DIGITS, "0": ["abcdef", "abcdefg"], "L": "def"}
    assert SevenSegment([2, 3, 4, 5, 6, 7, 8], font=font).read(trace, at_ms=10) == "0"
    unwired = SevenSegment([9, 10, 12, 13, 14, 15, 16])
    assert unwired.segments(trace, at_ms=10) == ""
    assert unwired.read(trace, at_ms=10) == " "
