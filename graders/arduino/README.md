# Arduino grader

The grader image compiles a submitted Uno sketch with the workspace's Arduino CLI and AVR core, runs it in [simavr](https://github.com/buserror/simavr), and scores it with the test functions in a question's `tests/test.py`. Tests drive the program's inputs, scripted ahead of time or in reaction to what it does, and check the recorded pin states and Serial traffic. Submissions can be the `sketch.ino` that `velxio.py` extracts from a workspace's `project.vlx`, or `.ino` files from `pl-file-editor` or `pl-file-upload`.

## Question setup

```json
"gradingMethod": "External",
"externalGradingOptions": {
  "image": "acha666/pl-workspace-velxio:arduino-grader-X.Y.Z",
  "timeout": 60
}
```

The image's entrypoint grades with the question's `tests/test.py`; set `entrypoint` only to run another file, such as `python3 -m arduinograder /grade/tests/other.py`. Give the question `autoPoints` in the assessment, since manual points alone never start the grader, and a `timeout` above `TIME_BUDGET_S` (25 s unless `test.py` sets it), which bounds compiling and simulating but not the tests' own Python code.

To try a test file without PrairieLearn, run it in the grader image on a sketch, which prints the results students would see as JSON:

```sh
docker run --rm -v "$PWD:/q" acha666/pl-workspace-velxio:arduino-grader-X.Y.Z \
    /q/questions/arduino/blinkWithoutDelay/tests/test.py --sketch /q/attempt.ino
```

`scripts/grade.py` does the same through PrairieLearn's file layout under production limits (no network, 0.9 CPU, 2 GiB), and `--cases` checks a directory of sketches against their expected scores; grade a correct solution and some wrong, partial and edge-case sketches before assigning a question. With `arduino-cli` and `avrsim` installed, `python3 -m arduinograder test.py --sketch FILE` grades outside the image too, each run in an unused `--work-dir` (default `/tmp/arduinograder`), with `--name` and `--params JSON` standing in for the submitted file name and the question's params.

## Writing tests

```python
import arduinograder as ag
from arduinograder.extras import no_calls

LEDS = (13, 9, 7)
BUTTON = 2

gates = [no_calls("delay")]
scenario = ag.Scenario(duration_ms=1850).pulse(BUTTON, ag.HIGH, at_ms=50, duration_ms=10)


@ag.points(8)
@ag.name("A single click starts Mode 1 after 500 ms")
def test_single_click(trace, check):
    check(trace.levels(LEDS, at_ms=350) == (0, 0, 0), "At 350 ms all LEDs should be off.")
    check(trace.levels(LEDS, at_ms=700) == (1, 1, 1), "At 700 ms all LEDs should be on.")


@ag.points(2)
def test_button_is_an_input(trace):
    assert trace.pin(BUTTON).at(10).is_input, "Pin 2 must be an input."
```

A test is a function decorated with `points()` that receives the fixtures it names as parameters. It passes unless it raises `AssertionError`, whose message the student sees, or records a failed `check()`, and it can return a number from 0 to 1 for partial credit, such as `check.fraction`, the share of checks that passed. Each test runs on its own, so an error in one is reported as a grader error for that test alone.

The `trace` fixture runs the module's `scenario`, a `Scenario` or a function returning one, or the test's own from `@ag.with_scenario(...)`; each distinct scenario is simulated once per submission.

Grading stops with zero points when a gate fails: the functions in `gates` and those decorated with `@ag.gate` run before the tests, take fixtures like a test, and fail by raising `ag.StopGrading(message)`, returning a message or failing an `assert`. A compile error is a gate that always applies, showing the student up to the first 20 errors. Raising `ag.Ungradable(message)` anywhere instead reports a submission that cannot be graded, as an unexpected error outside a test, a mistake in the test module or a wall-clock overrun does, and PrairieLearn does not count the attempt.

### Fixtures

| Fixture       | Value                                                                                   |
| ------------- | --------------------------------------------------------------------------------------- |
| `trace`       | The `Trace` of the sketch run through the module's or the test's scenario               |
| `simulate`    | `simulate(scenario)` runs the sketch through any `Scenario` and returns its `Trace`      |
| `session`     | `session()` starts the sketch in a `Session` to drive step by step; use it with `with`  |
| `check`       | Records expectations: `check(condition, message)`, `check.fail(message)`, `check.fraction` |
| `firmware`    | The compiled sketch; asking for it compiles once                                        |
| `source`, `sketch_name` | The submitted sketch's text and file name                                     |
| `submission`, `params`, `data` | The `Submission` with every submitted file; PrairieLearn's params and data |
| `tests_dir`   | The directory of `test.py`, for reference files kept next to it                         |
| `compiler`, `simulator` | The `Compiler` and `Simulator` behind the fixtures above                       |

The module may also set `TIME_BUDGET_S`, the wall-clock budget for compiling and simulating (25 by default), and `SKETCH_FILE`, the file to grade (`sketch.ino` by default, else the only `.ino` submitted).

### `Scenario`

Pins are Uno numbers 0-19 or `"A0"`-`"A5"`, times are milliseconds from reset, and an undriven input reads LOW, or HIGH with `INPUT_PULLUP`.

- `Scenario(duration_ms, max_pin_changes=200000, max_serial_bytes=65536)`
- `.set(pin, level, at_ms=0)` drives an input from outside, overriding the internal pull-up.
- `.release(pin, at_ms=0)` stops driving a pin, which then reads like an unconnected one: HIGH under the program's `INPUT_PULLUP`, else LOW.
- `.pulse(pin, level, at_ms=, duration_ms=)` drives a pin to `level` and releases it `duration_ms` later, as a button press does: `HIGH`, or `LOW` for a button to ground, after which the pin stays LOW if the sketch forgot `INPUT_PULLUP`.
- `.analog(pin, value, at_ms=0)` makes `analogRead()` return `value` (0-1023).
- `.send(text, at_ms=0)` sends text to the sketch's `Serial`, one byte per millisecond.

### `Trace`

A `Trace` records pin modes, output levels and Serial bytes against simulated time, except `analogWrite()` output, which reads as LOW or as the raw 976 Hz waveform on pins 5 and 6, so do not grade it.

- `.pin(pin)` gives a `PinTrace`:
  - `.at(ms)` is a `PinState`, `HIGH`, `LOW`, `INPUT` or `INPUT_PULLUP`, with `.is_high`, `.is_low`, `.is_output`, `.is_input` and `.level` (1, 0 or `None` for an input).
  - `.level(ms)` is that level directly; `trace.levels(pins, at_ms)` gives a tuple for several pins.
  - `.changes(start_ms, end_ms)` lists every `Change(time_ms, state)`, including mode changes.
  - `.edges(start_ms, end_ms)` lists each `Edge(time_ms, level)` where the output level flipped (an input switched straight to HIGH has none), with `.rising()`, `.falling()`, `.times_ms`, `.intervals_ms()`, `.describe()` for messages, and `.match(times_ms, tolerance_ms=)` and `.periodic(period_ms, tolerance_ms=)`, which compare times only, so match `.rising()` and `.falling()` separately to check direction.
  - `.high_fraction(start_ms, end_ms)` is the share of the interval the pin was driven HIGH; `.stable(start_ms, end_ms)` is true if it did not change.
- `.serial.text(start_ms, end_ms)`, `.serial.lines(...)` as `Line(time_ms, text)` timed by each newline, and `.serial.bytes(...)`.
- `.end_ms` and `.stop_reason`, `"end"` unless the program crashed, hit a limit or finished (`"done"`: `exit()`, or an endless loop or sleep with interrupts disabled); asking about a later time raises `SimulationStopped`, which fails the current test with an explanation, and a time after the scenario raises `ValueError`.

### `Session`

A session runs the sketch from reset and lets a test react to it, advancing time only when asked and applying inputs at the current time:

```python
@ag.points(5)
def test_responds_to_the_button(session):
    with session() as run:
        lit_at = run.wait_for(LED, "HIGH", timeout_ms=1000)
        assert lit_at is not None, "The LED should turn on within a second."
        run.pulse(BUTTON, ag.HIGH, duration_ms=20)  # the LED goes off during the press
        off_at = run.wait_for(LED, "LOW", timeout_ms=100)
        assert off_at is not None, "The press should turn the LED off."
        line = run.wait_for_line(timeout_ms=100)
        assert line and line.text == "pressed", "Serial should report the press."
```

- `.run_until(ms)` and `.run_for(ms)` advance time, returning `False` once the program has stopped.
- `.set()`, `.release()`, `.analog()`, `.send()` and `.pulse(pin, level, duration_ms=)` as in `Scenario`, applied now; `pulse()` advances time by its duration.
- `.wait_for(pin, state=None, timeout_ms=)` returns the time of the pin's first change (to `state`, if given) not yet returned, at once if it already happened, say during a `pulse()`, else after running until it happens, or `None` once `timeout_ms` have passed since `now_ms`.
- `.wait_for_line(timeout_ms=)` does the same for the program's Serial lines; an input through `set()`, `analog()`, `send()` or `pulse()`, but not `release()`, starts both waits afresh, so what the program did before it is never taken for a reaction.
- `.now_ms`, `.state(pin)`, `.running`, `.stop_reason`, and `.trace`, the `Trace` of everything so far, for checks over the whole run.
- `session(max_pin_changes=..., max_serial_bytes=...)` sets the limits.

## Extras

`arduinograder.extras` holds helpers that encode a grading policy or assume a circuit, so import one only when the question needs it; the core API can express the same checks.

### Forbidding calls

```python
from arduinograder.extras import find_calls, no_calls
```

`gates = [no_calls("delay", "delayMicroseconds")]` stops grading with score 0, listing up to three offending lines, if the sketch calls any named function, and `find_calls(source, *names)` returns the calls, each with `name`, `line` and `text`, for a test that only takes off points:

```python
@ag.points(1)
def test_no_delay(source):
    assert not find_calls(source, "delay"), "Use millis() instead of delay()."
```

Both parse the source with tree-sitter, ignoring comments, strings and methods of the same name (`obj.delay()`) but not seeing through macros, function pointers or wrappers, so where blocking code matters, a behavioural test (a button must respond while the LEDs blink) is harder to get around.

### Seven-segment displays

`SevenSegment(pins, common="cathode")` reads one digit of Velxio's display, segments A-G and the decimal point DP, from the eight pins given in that order, with `None` for a segment that is not wired. `.segments(trace, at_ms)` gives the lit segments as a `Segment` set, counting unwired segments and input pins as off. Combine segments with `|`, test one with `S.DP in lit`, ignore one with `lit & ~S.DP`, or convert an Arduino digit byte with `Segment(0x3F)` (bit 0 is A, bit 7 is DP); in messages a set prints as `A, B, C`, or `none`. Velxio lights a segment whenever its pin is HIGH, whatever the display's `common` setting, so use `common="anode"` only for sketches written for a real common-anode display, and read a multiplexed display's digit-select pins with `Trace`, as it is not covered.

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
scenario = ag.Scenario(duration_ms=10000)


@ag.points(5)
@ag.name("Shows 0 to 9, one second each")
def test_counts(trace, check):
    for digit in range(10):
        at_ms = digit * 1000 + 500
        lit = DISPLAY.segments(trace, at_ms)
        check(
            lit in DIGITS[digit],
            f"At {at_ms} ms the display should show {digit}; lit segments: {lit}.",
        )
    return check.fraction
```

## How grading runs

- `python -m arduinograder`, the image's entrypoint, grades the submission under `/grade` with `/grade/tests/test.py` and writes `results/results.json`. A test file ending in `if __name__ == "__main__": ag.main()` runs the same way, the guard being needed because the grader imports the file.
- Everything under `/grade` except `results/` is readable only by root, and compilation and simulation run as `sbuser`, so a sketch cannot `#include` the tests or `data.json`, though solutions still do not belong in `tests/`. Started as another user, the grader refuses to grade rather than expose the tests.
- The compiler and simulator start under generous per-process limits on CPU time, memory and file size, and a sketch whose compilation hits one scores 0 with that explanation.
- Simulation runs in simulated time, taking about a tenth of it in wall-clock on one CPU, so the same sketch and inputs always give the same trace whatever the server load; a wall-clock overrun means the server was too slow, and the submission is reported as ungradable rather than scored.
- The grader drives and reads the microcontroller's pins directly and does not simulate the Velxio circuit, so questions fix the wiring and pin numbers their tests use, and the submitted `project.vlx` is not graded.

## Development

`graders/arduino` is a member of the repository's [uv](https://docs.astral.sh/uv/) workspace, sharing the root `uv.lock` and lint settings:

```sh
cd graders/arduino
uv sync              # the environment, with the package installed editable
uv run ruff check .  # lint; uv run ruff format . formats
uv run mypy          # strict type checking of src/ and tests/
uv run pytest        # tests that need arduino-cli and avrsim are skipped unless installed
```

The grader image installs the package from the same lock, and its `grader-test` target runs the three checks with the toolchain present. The package is fully typed (`py.typed`), checked with `mypy --strict`, and documented with Google-style docstrings.

| Path                             | Contents                                                                                      |
| -------------------------------- | --------------------------------------------------------------------------------------------- |
| `pyproject.toml`                 | The `arduinograder` package: dependencies, `arduinograder` command, mypy and pytest settings  |
| `src/arduinograder/cli.py`       | The `arduinograder` command: `main()`                                                         |
| `src/arduinograder/grading.py`   | The fixtures tests receive; `Grading`, one run of a module's gates and tests; `grade()`       |
| `src/arduinograder/pl.py`        | PrairieLearn's layout: `Submission`, `Results` and hiding `/grade` from the sandbox user       |
| `src/arduinograder/rubric.py`    | `points()`, `name()`, `gate()`, `Check`; collecting and running tests in isolation            |
| `src/arduinograder/sandbox.py`   | The work directory, the `sbuser` account, the per-process `Limits` and the wall-clock `Budget` |
| `src/arduinograder/toolchain.py` | `Compiler`, `Firmware` and `CompileError`                                                     |
| `src/arduinograder/sim/`         | `Scenario`, `Session`, `Simulator` and `Trace`, over the `avrsim` line protocol               |
| `src/arduinograder/board.py`     | Pin names and simulated time                                                                  |
| `src/arduinograder/errors.py`    | `Ungradable`, `StopGrading` and the messages students see when grading ends early             |
| `src/arduinograder/extras/`      | Optional helpers: call checks and seven-segment displays                                      |
| `avrsim/avrsim.c`                | The simavr wrapper                                                                            |
| `tests/`                         | The package's tests, one file per module, and the template regression `cases/`                |

`avrsim/avrsim.c` wraps simavr as a long-running process whose protocol is documented at the top of the file: the grader sends inputs and `run` commands on its stdin and reads pin changes, Serial bytes and stop reasons from its stdout, so a test can react to the program mid-run.
