# Changelog

## Unreleased

The grader's test API is redesigned, and the repository is laid out for several graders and workspace images. The workspace image only moved its sources.

### Upgrading from 2.0.0

- Rewrite `tests/test.py` as test functions; the `ArduinoGrader` class is gone, and its `time_budget_s` becomes the module setting `TIME_BUDGET_S`, 25 s by default. `blinkWithoutDelay` shows the conversion.
- Remove `entrypoint` from `externalGradingOptions`; the image's entrypoint grades with `/grade/tests/test.py`.
- `trace.state(pin, ms)` becomes `trace.pin(pin).at(ms)`; `level()` and `changes()` move to `trace.pin(pin)` too, and `serial_text()`/`serial_lines()` become `trace.serial.text()`/`.lines()`.
- `Scenario.press()` becomes `pulse()`, `forbid_calls()` becomes `gates = [no_calls(...)]`, and `find_calls()` takes names as positional arguments.

### Grader

- Tests are functions decorated with `@ag.points()` that receive fixtures by name: `trace`, `simulate`, `session`, `check`, `source` and more. Each runs on its own; a returned fraction gives partial credit.
- `gates` and `@ag.gate` functions run first and stop grading with zero points, as does a compile error; a mistake in the test module makes the submission ungradable.
- The `session` fixture drives the sketch step by step: `wait_for()` a pin change or `wait_for_line()`, then `pulse()`, `set()`, `analog()` or `send()`; waits never miss a reaction.
- `pulse()` and `release()` leave a pin reading like an unconnected one, HIGH under `INPUT_PULLUP` and LOW without it, so a missing pull-up shows.
- `Trace` is typed: `PinState` has `.is_high` and `.level`; `edges()` has `.match()`, `.periodic()` and `.describe()`; Serial and interval queries take time windows.
- `--sketch FILE` grades a local file and prints the results; the work directory is no longer cleared, so name an unused `--work-dir` for each local run.
- The compiler and simulator run under CPU, memory and file-size limits; a compilation that hits one scores 0 with an explanation. Feedback is capped at 8000 characters.

### Questions

- New `modeSwitch` template: a debounced button, a long press, Serial commands and a potentiometer drive three LEDs; its tests mix `session` reactions with `trace` checks.
- `blinkWithoutDelay` uses the new API and also forbids `delayMicroseconds()`. `velxio.py` rejects submissions carrying their own `_files`.

### Repository

- The grader lives in `graders/arduino/` and the workspace sources in `workspaces/arduino/`; `graders/*` form a uv workspace with one `uv.lock`.
- The Dockerfile fetches and patches Velxio itself, with every pin at its top; `scripts/prepare.py`, `.build` and `toolchain.lock.json` are gone.
- `docker-bake.hcl` defines the targets: `docker buildx bake test` runs the tests in parallel and `docker buildx bake --load` builds both `:dev` images.
- CI runs ruff, `mypy --strict` and the toolchain-free tests without Docker first, then builds and tests the images through the same bake file.

## 2.0.0 — 2026-10-20

- Images are tagged `arduino-workspace-X.Y.Z` and `arduino-grader-X.Y.Z`; the 1.0.0 workspace keeps its `arduino-1.0.0` tags.
- New `arduino-grader-` image: compiles with the workspace toolchain, simulates in simavr on scripted inputs, and runs a question's `tests/test.py` written with `arduinograder`.
- Compilation and simulation run as an unprivileged user that cannot read `/grade`; simulated time makes results independent of server load.
- `blinkWithoutDelay` autograded template, `scripts/grade.py` for local grading, and `arduinograder.extras` with `forbid_calls()`, `find_calls()` and `SevenSegment`. `analogWrite()` is not supported.
- The workspace status bar is replaced by the save icon above the file list; saves happen 3 s after edits pause and retry on failure.
- Repository reorganized into `workspace/`, `grader/` and `course/`, with one `toolchain.lock.json`, a root `Dockerfile` and tests under `tests/`.

## 1.0.0 — 2026-09-22

Initial release for PrairieLearn workspaces on Linux AMD64.

- Native Velxio code and circuit editing for one Arduino Uno and `sketch.ino`, with offline compilation on the Arduino AVR 1.8.6 core.
- Atomic `project.vlx` saves, revision conflict detection and local recovery export.
- Blink and seven-segment templates with submitted sketch previews for manual grading.
- Container tests through a PrairieLearn-style proxy, not a live deployment; pinned upstream source, dependency locks and a downloadable adapter source archive.
