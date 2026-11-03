# Changelog

## Unreleased

The grader's test API is redesigned, and the repository is laid out for more than one grader and workspace image. The workspace image is unchanged apart from where its sources live.

### Upgrading from 2.0.0

- Rewrite each question's `tests/test.py` as test functions: the `ArduinoGrader` class with `tests()`, `self.test()`, `self.compile()` and `self.simulate()` is removed. `course/questions/arduino/blinkWithoutDelay/tests/test.py` shows the conversion.
- Remove `entrypoint` from `externalGradingOptions`. The image's entrypoint, `python3 -m arduinograder`, grades with `/grade/tests/test.py`.
- `trace.state(pin, at_ms)` becomes `trace.pin(pin).at(ms)`, which returns a `PinState` instead of a string; `trace.level()` and `trace.changes()` move to `trace.pin(pin)` as well, and `trace.serial_text()` and `serial_lines()` become `trace.serial.text()` and `.lines()`.
- `Scenario.press()` becomes `pulse()`, and `forbid_calls()` at the start of `tests()` becomes `gates = [no_calls(...)]`.

### Grader

- Tests are functions decorated with `@ag.points()` that receive fixtures such as `trace`, `simulate`, `session`, `check` and `source` by naming them as parameters. Each test runs on its own, so an error fails only that test; returning a number from 0 to 1, such as `check.fraction`, gives partial credit. `gates` and `@ag.gate` functions run first and can stop grading with zero points.
- The `session` fixture runs the sketch step by step, so a test can react to it: `wait_for()` a pin change or `wait_for_line()` from Serial, then `pulse()`, `set()`, `analog()` or `send()`. Waits hand out what the program did in order, at once when it has already happened, so a reaction during a `pulse()` is not missed and a line printed before an input is not taken for its reply. `avrsim` is now a long-running process driven over stdin and stdout.
- `pulse(pin, level, ...)` drives a pin and then releases it, and `release(pin)` releases it alone. A released pin reads like an unconnected one, HIGH under `INPUT_PULLUP` and LOW without it, so a test can catch a missing pull-up. `Scenario.send()` writes to the sketch's Serial at one byte per millisecond.
- `Trace` is typed: `PinState` has `.is_high`, `.is_output` and `.level`; `trace.pin(13).edges()` lists output level flips with `.match()`, `.periodic()` and `.describe()`; `.high_fraction()` and `.stable()` summarise intervals; `trace.serial.lines()` and `.text()` accept time windows.
- `--sketch FILE` grades a local file and prints the results, with `python3 -m arduinograder` or a test file ending in `ag.main()`.
- The compiler and simulator run under per-process limits on CPU time, memory and file size, without supplementary groups; a compilation that hits a limit scores 0 with an explanation, and the compiler stops after 20 errors. The grader refuses to grade unless it can hand compiling and simulating to the sandbox user, and a spent time budget stops the simulator at once.

### Questions

- New `modeSwitch` autograded template: a debounced button cycles modes shown on three LEDs, a long press returns to mode 0, `mode N` on Serial sets a mode, and a potentiometer sets the blink period of mode 3. Its tests combine `session` reactions with `trace` checks.
- `blinkWithoutDelay` uses the new API and no longer sets `entrypoint`.

### Repository

- The Arduino grader is in `graders/arduino/` and the Arduino workspace sources in `workspaces/arduino/`, each with its tests and, for the grader, its regression cases; `tests/` keeps the course template tests.
- Both images build straight from the repository. The Dockerfile fetches the pinned Velxio commit and applies the patches, adapter and dependency locks itself, so `scripts/prepare.py`, the prepared `.build` context and `toolchain.lock.json` are gone, and every pin is at the top of the Dockerfile; `--build-context velxio-upstream=PATH` builds from a local Velxio checkout. The workspace's source archive holds the build files and `workspaces/`, and `run.sh` checks that it holds no course files or graders and that the image rebuilds from it.
- `graders/*` are members of a [uv](https://docs.astral.sh/uv/) workspace with one `uv.lock`, from which the grader image installs `arduinograder`. The package is split by responsibility (`rubric`, `grading`, `sim`, `sandbox`, `toolchain`, `pl`, `cli`), fully typed with Google-style docstrings, and `grader-test` runs ruff, `mypy --strict` and pytest.

## 2.0.0 — 2026-10-20

- Images are tagged `arduino-workspace-X.Y.Z` and `arduino-grader-X.Y.Z`. The 1.0.0 workspace keeps its `arduino-1.0.0` tags; update question `info.json` files when upgrading.
- New `arduino-grader-` image for PrairieLearn external grading: compiles with the workspace toolchain, simulates in simavr on scripted inputs, and runs a question's `tests/test.py` written with the `arduinograder` package.
- Compilation and simulation run as an unprivileged user that cannot read `/grade`; simulated time makes results independent of server load.
- `blinkWithoutDelay` autograded template. `scripts/grade.py` grades sketches under production grader limits. Optional helpers in `arduinograder.extras` serve questions that need them: `forbid_calls()` and `find_calls()`, and `SevenSegment`, which reads a display's lit segments (A-G and DP, as in Velxio) as a `Segment` set; each question defines which shapes count as which digit. `analogWrite()` output is not supported yet.
- Template grader cases are temporary regression tests in `tests/grader/cases/`, outside the question directories.
- Submissions list the extracted `sketch.ino` before `project.vlx`.
- The workspace status bar is removed. The save icon above the file list is the only save control, with a quiet status such as “Saved 5:02 PM” beside it. The icon no longer flashes while typing and changes only when a save is overdue or fails. Changes save 3 s after editing pauses, at least every 30 s while editing and when leaving the workspace, and failed saves retry automatically. **Source & licenses** moved to the Help menu.
- Repository reorganized into `workspace/`, `grader/` and `course/` with one `toolchain.lock.json` and a root `Dockerfile`; the upstream patch is split by topic. Tests are in `tests/`, one folder per component; the workspace image test is `tests/workspace/run.sh`.

## 1.0.0 — 2026-09-22

Initial release for PrairieLearn workspaces on Linux AMD64.

- Native Velxio code and circuit editing for one Arduino Uno and `sketch.ino`.
- Offline compilation with the preinstalled Arduino AVR 1.8.6 core.
- Atomic `project.vlx` saves, revision conflict detection and local recovery export.
- Blink and seven-segment question templates with submitted sketch previews for manual grading.
- Container tests for persistence, compilation and Chromium simulation through a PrairieLearn-style proxy.
- Pinned upstream source, dependency locks and a downloadable adapter source archive.

Validation uses a local PrairieLearn-style proxy; it does not include a live PrairieLearn deployment or submission test.
