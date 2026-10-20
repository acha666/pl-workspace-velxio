# Arduino grader

The grader image compiles a submitted Uno sketch with the workspace's Arduino CLI and AVR core, runs it in [simavr](https://github.com/buserror/simavr) through scripted inputs, and lets a question's `tests/test.py` check the recorded pin states and Serial output. It works with Velxio workspace submissions (`sketch.ino`, extracted by `velxio.py`) and with `.ino` files from `pl-file-editor` or `pl-file-upload`.

## Question setup

```json
"gradingMethod": "External",
"externalGradingOptions": {
  "image": "acha666/pl-workspace-velxio:arduino-grader-X.Y.Z",
  "entrypoint": "python3 /grade/tests/test.py",
  "timeout": 60
}
```

Give the question `autoPoints` in the assessment; PrairieLearn does not run the grader for questions with only manual points. Keep `ArduinoGrader.time_budget_s` (45 s by default) below the timeout.

`scripts/grade.py` grades sketches with a question's tests without PrairieLearn, in the grader image under production limits (no network, 0.9 CPU, 2 GiB). Grade a correct solution and some wrong, partial and edge-case sketches, with `--verbose` to read the feedback students will see:

```sh
python3 scripts/grade.py --image acha666/pl-workspace-velxio:arduino-grader-X.Y.Z questions/.../myQuestion reference.ino
python3 scripts/grade.py --verbose questions/.../myQuestion my-attempt.ino
```

## Writing tests

```python
import arduinograder as ag

LEDS = (13, 9, 7)
BUTTON = 2


class QuestionGrader(ag.ArduinoGrader):
    def tests(self):
        firmware = self.compile()  # score 0 with compiler errors if it fails
        trace = self.simulate(
            firmware, ag.Scenario(duration_ms=1850).press(BUTTON, at_ms=50, hold_ms=10)
        )
        with self.test("A single click starts Mode 1 after 500 ms", points=8) as test:
            test.expect(trace.levels(LEDS, at_ms=350) == (0, 0, 0), "At 350 ms all LEDs should be off.")
            test.expect(trace.levels(LEDS, at_ms=700) == (1, 1, 1), "At 700 ms all LEDs should be on.")


if __name__ == "__main__":
    QuestionGrader().start()
```

Each `test()` awards all or none of its points; every failed `expect()` message is shown.

### `ArduinoGrader`

| Member                         | Purpose                                                                              |
| ------------------------------ | ------------------------------------------------------------------------------------ |
| `compile()`                    | Compile the sketch and return the firmware; stops with score 0 if compilation fails  |
| `simulate(firmware, scenario)` | Run from reset through the scenario and return a `Trace`                             |
| `test(name, points)`           | Context manager collecting one test's `expect(condition, message)` and `fail(message)` |
| `add_message(text)`            | Add text to the overall feedback                                                     |
| `source`, `params`, `data`     | Submitted sketch text; `params` and the full `data` from PrairieLearn                |
| `sketch_file`                  | Submitted file name; default `sketch.ino`, else the only `.ino` submitted            |
| `time_budget_s`                | Wall-clock budget for compiling and simulating                                       |

Raise `ag.StopGrading(message)` to end with score 0, or `ag.Ungradable(message)` when the submission cannot be graded (PrairieLearn does not count the attempt).

### `Scenario` and `Trace`

Pins are Uno numbers 0-19 or `"A0"`-`"A5"`; times are milliseconds from reset.

- `Scenario(duration_ms, max_pin_changes=200000, max_serial_bytes=65536)`
  - `.set(pin, level, at_ms=0)` drives an input from outside, overriding the internal pull-up. Undriven inputs read LOW, or HIGH with `INPUT_PULLUP`.
  - `.press(pin, at_ms=, hold_ms=, active=HIGH)` presses and releases a button; use `active=LOW` for a button to ground.
  - `.analog(pin, value, at_ms=0)` makes `analogRead()` return `value` (0-1023).
- `Trace`
  - `.state(pin, at_ms)` gives `"HIGH"`, `"LOW"`, `"INPUT"` or `"INPUT_PULLUP"` as set by the program.
  - `.level(pin, at_ms)` gives 1 or 0 for an output and `None` for an input, including a pin read with `analogRead()`; `.levels(pins, at_ms)` gives a tuple. `analogWrite()` is [not supported yet](#not-supported-yet).
  - `.changes(pin, start_ms=0, end_ms=None)` lists `(time_ms, state)` changes.
  - `.serial_text()` and `.serial_lines()`, the latter as `(time_ms, text)` timed by each newline.
  - `.stop_reason` is `"end"` unless the program crashed or exceeded a limit. Asking about a later time then raises `SimulationStopped`, which fails the current test with an explanation.

## Features for special-purpose questions

`arduinograder.extras` holds helpers for particular question designs. Each encodes a grading policy or assumes a circuit, so import one only when the question needs it; the core API above can express the same checks.

### Forbidding calls

```python
from arduinograder.extras import find_calls, forbid_calls
```

`forbid_calls(self.source, "delay", "delayMicroseconds")` stops grading with score 0, listing up to three offending lines, if the sketch calls any named function. `find_calls(source, names)` returns the calls, each with `name`, `line` and `text`, without stopping; use it to take off only some points:

```python
with self.test("Does not call delay()", points=1) as test:
    test.expect(not find_calls(self.source, ["delay"]), "Use millis() instead of delay().")
```

Both parse the source with tree-sitter: comments, strings and methods with the same name (`obj.delay()`) are ignored, but calls hidden behind macros, function pointers or wrapper functions are not found. Where blocking code matters, a behavioural test (for example, a button must respond while the LEDs blink) is harder to get around.

### Seven-segment displays

`SevenSegment(pins, common="cathode")` reads one digit of Velxio's display, which has segments A-G and the decimal point DP. Give the eight pins in that order, with `None` for a segment that is not wired. `.segments(trace, at_ms)` gives the lit segments as a `Segment` set; unwired segments and input pins count as off. Combine segments with `|`, test one with `S.DP in lit`, ignore one with `lit & ~S.DP`, or convert an Arduino digit byte with `Segment(0x3F)` (bit 0 is A, bit 7 is DP). In messages a set prints as `A, B, C`, or `none`.

Which shapes count as which digit is up to each question, so define them in `tests/test.py`:

```python
import arduinograder as ag
from arduinograder.extras import Segment as S
from arduinograder.extras import SevenSegment

DISPLAY = SevenSegment([2, 3, 4, 5, 6, 7, 8, None])  # A-G and DP; DP is not wired
# Accepted shapes; this question allows 6, 7 and 9 with or without tails.
DIGITS = {
    0: {S.A | S.B | S.C | S.D | S.E | S.F},
    1: {S.B | S.C},
    2: {S.A | S.B | S.D | S.E | S.G},
    3: {S.A | S.B | S.C | S.D | S.G},
    4: {S.B | S.C | S.F | S.G},
    5: {S.A | S.C | S.D | S.F | S.G},
    6: {S.A | S.C | S.D | S.E | S.F | S.G, S.C | S.D | S.E | S.F | S.G},
    7: {S.A | S.B | S.C, S.A | S.B | S.C | S.F},
    8: {S.A | S.B | S.C | S.D | S.E | S.F | S.G},
    9: {S.A | S.B | S.C | S.D | S.F | S.G, S.A | S.B | S.C | S.F | S.G},
}


class QuestionGrader(ag.ArduinoGrader):
    def tests(self):
        trace = self.simulate(self.compile(), ag.Scenario(duration_ms=10000))
        with self.test("Shows 0 to 9, one second each", points=5) as test:
            for digit in range(10):
                at_ms = digit * 1000 + 500
                lit = DISPLAY.segments(trace, at_ms)
                test.expect(lit in DIGITS[digit], f"At {at_ms} ms the display should show {digit}; lit segments: {lit}.")


if __name__ == "__main__":
    QuestionGrader().start()
```

- The grader does not see the Velxio circuit: give the pins that the question's project uses.
- Velxio lights a segment whenever its pin is HIGH and ignores the display's `common` setting, as a common cathode would. Use `common="anode"` only for sketches written for a real common-anode display outside Velxio.
- Multiplexed multi-digit displays are not covered; read the digit-select pins with `Trace`.

## Not supported yet

- `analogWrite()` output. The trace records no PWM duty cycle, so do not grade it. On pins 3, 9, 10 and 11, values 1-254 read as LOW; pins 5 and 6 record the raw 976 Hz waveform, whose edges count toward `max_pin_changes`.

## How grading runs

- `/grade` is made readable only by root. Compilation and simulation run as `sbuser`, so a sketch cannot `#include` the tests or `data.json`. Never put solutions in `tests/`.
- Simulation uses simulated time only: the same sketch and scenario always give the same trace, whatever the server load. A wall-clock overrun means the server was too slow; the submission is reported as ungradable rather than scored.
- The grader drives and reads the microcontroller's pins directly. It does not simulate the Velxio circuit, so questions must fix the wiring and pin numbers.
