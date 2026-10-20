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

```
questions/.../myQuestion/
├── tests/test.py          tests run by the grader
└── grader-cases/          not sent to the grader
    ├── reference.ino      a correct solution, expected to score 1.0
    ├── *.ino              wrong, partial and edge-case submissions
    └── expected.json      {"reference.ino": 1.0, "uses-delay.ino": 0.0, ...}; null = ungradable
```

Check every case under production limits (no network, 0.9 CPU, 2 GiB), or grade one sketch with `--verbose` to see the feedback:

```sh
python3 scripts/grade.py --image acha666/pl-workspace-velxio:arduino-grader-X.Y.Z questions/.../myQuestion
python3 scripts/grade.py --verbose questions/.../myQuestion my-attempt.ino
```

## Writing tests

```python
import arduinograder as ag

LEDS = (13, 9, 7)
BUTTON = 2


class QuestionGrader(ag.ArduinoGrader):
    def tests(self):
        self.forbid_calls("delay", "delayMicroseconds")  # score 0 if called
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

Each `test()` awards all or none of its points; every failed `expect()` message is shown. The score is the fraction of points earned. Write messages for students: say what the test did and what was expected at which time.

### `ArduinoGrader`

| Member                         | Purpose                                                                              |
| ------------------------------ | ------------------------------------------------------------------------------------ |
| `compile()`                    | Compile the sketch and return the firmware; stops with score 0 if compilation fails  |
| `forbid_calls(*names)`         | Stop with score 0 if the sketch calls any named function (comments and strings are ignored) |
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
  - `.level(pin, at_ms)` gives 1 or 0 for an output and `None` for an input; `.levels(pins, at_ms)` gives a tuple.
  - `.changes(pin, start_ms=0, end_ms=None)` lists `(time_ms, state)` changes.
  - `.serial_text()` and `.serial_lines()`, the latter as `(time_ms, text)` timed by each newline.
  - `.stop_reason` is `"end"` unless the program crashed or exceeded a limit. Asking about a later time then raises `SimulationStopped`, which fails the current test with an explanation.
- `SevenSegment(pins_a_to_g, common="cathode", font=DIGITS)`: `.read(trace, at_ms)` gives the character shown (blank is `" "`, unknown patterns `None`); `.segments(trace, at_ms)` gives the lit segments, e.g. `"bc"`. A font maps characters to segment letters or lists of accepted alternatives.

## How grading runs

- `/grade` is made readable only by root. Compilation and simulation run as `sbuser`, so a sketch cannot `#include` the tests or `data.json`. Never put solutions in `tests/`; keep them in `grader-cases/`.
- Simulation uses simulated time only: the same sketch and scenario always give the same trace, whatever the server load. A wall-clock overrun means the server was too slow; the submission is reported as ungradable rather than scored.
- The grader drives and reads the microcontroller's pins directly. It does not simulate the Velxio circuit, so questions must fix the wiring and pin numbers.
- simavr does not generate phase-correct PWM waveforms, which `analogWrite()` uses on pins 3, 9, 10 and 11. PWM on pins 5 and 6 is recorded.
- Static checks cannot see calls hidden behind macros or function pointers. Prefer behavioural tests (for example, a button must respond while the LEDs blink) where blocking code matters.
