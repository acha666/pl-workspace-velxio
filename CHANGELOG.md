# Changelog

## Unreleased

The grader's test API is redesigned, and the repository is laid out for more than one grader and workspace image. The workspace image is unchanged apart from where its sources live.

### Upgrading from 2.0.0

- Rewrite each question's `tests/test.py` as test functions; the `ArduinoGrader` class with `tests()`, `self.test()`, `self.compile()` and `self.simulate()` is gone. `blinkWithoutDelay` shows the conversion.
- Remove `entrypoint` from `externalGradingOptions`; the image's entrypoint, `python3 -m arduinograder`, grades with `/grade/tests/test.py`.
- `trace.state(pin, at_ms)` becomes `trace.pin(pin).at(ms)` and returns a `PinState`, not a string; `trace.level()` and `trace.changes()` move to `trace.pin(pin)` too.
- `trace.serial_text()` and `trace.serial_lines()` become `trace.serial.text()` and `trace.serial.lines()`.
- `Scenario.press()` becomes `pulse()`; `forbid_calls()` at the start of `tests()` becomes `gates = [no_calls(...)]`.
- `find_calls(source, ["delay"])` becomes `find_calls(source, "delay")`, taking the names as `no_calls()` does.

### Grader

- Tests are functions decorated with `@ag.points()`; they receive fixtures such as `trace`, `simulate`, `session`, `check` and `source` by naming them as parameters.
- Each test runs on its own, so an error fails only that test. Returning a number from 0 to 1, such as `check.fraction`, gives partial credit.
- `gates` and `@ag.gate` functions run before the tests and stop grading with zero points through `ag.StopGrading`, a returned message or a failed `assert`.
- When any test needs the firmware, the sketch is compiled right after the gates: a compile error stops grading before any test, showing up to 20 errors.
- The `session` fixture runs the sketch step by step: `wait_for()` a pin change or `wait_for_line()` from Serial, then `pulse()`, `set()`, `analog()` or `send()`.
- Waits hand out what the program did in order, at once when it already happened, so a reaction during a `pulse()` is not missed.
- An input starts the waits afresh: what the program printed before it is not taken for its reply.
- `avrsim` is now a long-running process driven over stdin and stdout, so a test can react to the sketch mid-run.
- `pulse(pin, level, ...)` drives a pin and then releases it; `release(pin)` releases it alone. Levels must be 1/0, a bool, `"HIGH"`/`"LOW"` or a `PinState`.
- A released pin reads like an unconnected one, HIGH under `INPUT_PULLUP` and LOW without it, so a test can catch a missing pull-up.
- `Scenario.send()` writes to the sketch's Serial at one byte per millisecond.
- `Trace` is typed: `PinState` has `.is_high`, `.is_output` and `.level`; `trace.pin(13).edges()` lists output level flips with `.match()`, `.periodic()` and `.describe()`.
- `.high_fraction()` and `.stable()` summarise intervals; `trace.serial.lines()` and `.text()` accept time windows. A window starting after the run ended raises, as `at()` does.
- `--sketch FILE` grades a local file and prints the results, through `python3 -m arduinograder` or a test file ending in `ag.main()` under the `__main__` guard.
- The test module is loaded as when run directly, so it can import a helper module next to it and use `from __future__ import annotations`.
- `TIME_BUDGET_S`, the wall-clock budget for compiling and simulating, defaults to 25 s and must be a positive, finite number.
- Mistakes in the test module, such as an unknown fixture or no tests worth points, make every submission ungradable instead of scoring it 0.
- The compiler and simulator run under per-process limits on CPU time, memory and file size, without supplementary groups. A compilation that hits one scores 0 with an explanation.
- The compiler CPU limit is 10 s, so a runaway compilation is reported within the default 25 s budget at 0.9 CPU.
- The grader refuses to grade unless it can hand compiling and simulating to the sandbox user; a spent time budget stops the simulator at once.
- Work directories must be missing or empty and cannot be symlinks; `--work-dir` never deletes existing contents.
- Each compiled firmware is kept in its own file, so a test compiling a reference sketch does not replace the student's.
- Awarded points are not rounded, so full marks with points such as 1/7 score exactly 1. A NaN or infinite result never reaches `results.json`.
- Each test's message and the overall one are cut to 8000 characters, and `edges().describe()` lists 25 times, keeping `results.json` under PrairieLearn's limit.
- Several `.ino` files without a `sketch.ino` are named instead of reported as a missing submission; a `sketch.ino` that is a symbolic link is not graded.
- `scripts/grade.py` prints scores with four decimals, so a score PrairieLearn rejects, such as 1.0003, shows.

### Questions

- New `modeSwitch` autograded template: a debounced button cycles modes shown on three LEDs, a long press returns to mode 0, and `mode N` on Serial sets a mode.
- In `modeSwitch`, a potentiometer sets the blink period of mode 3; its tests combine `session` reactions with `trace` checks.
- `blinkWithoutDelay` uses the new API, no longer sets `entrypoint`, and forbids `delayMicroseconds()` as well as `delay()`.
- `velxio.py` rejects a submission that carries its own `_files` and requires exactly one `project.vlx`, so only the workspace's sketch is graded.

### Repository

- The Arduino grader is in `graders/arduino/` and the Arduino workspace sources in `workspaces/arduino/`, each with its tests; `tests/` keeps the course template tests.
- The grader's template regression cases moved to `graders/arduino/tests/cases/`.
- Both images build straight from the repository: the Dockerfile fetches the pinned Velxio commit and applies the patches, adapter and dependency locks itself.
- `scripts/prepare.py`, the prepared `.build` context and `toolchain.lock.json` are gone; every pin is at the top of the Dockerfile.
- A local Velxio checkout builds through the `velxio-upstream` build context, for example `--set '*.contexts.velxio-upstream=PATH'` with bake.
- The workspace's source archive holds only the build files and `workspaces/`; `run.sh` checks it has no course files or graders and that the image rebuilds from it.
- `docker-bake.hcl` defines the image and test targets: `docker buildx bake test` runs the test targets in parallel, `docker buildx bake --load` builds `pl-arduino-workspace:dev` and `pl-arduino-grader:dev`.
- CI builds through the same file, with each image's layers cached in its own GitHub Actions cache scope.
- CI first checks the repository without Docker: ruff lint and format, `mypy --strict`, the grader tests that need no toolchain, and the course template tests.
- The image job, and so a release, runs only when those checks pass. The course template tests moved from `backend-test` to `uv run pytest` at the root.
- `graders/*` are members of a [uv](https://docs.astral.sh/uv/) workspace with one `uv.lock`, from which the grader image installs `arduinograder`.
- The package is split by responsibility (`rubric`, `grading`, `sim`, `sandbox`, `toolchain`, `pl`, `cli`), fully typed with Google-style docstrings; `grader-test` runs ruff, `mypy --strict` and pytest.
- Scripts, tests and course files are formatted with ruff.

## 2.0.0 — 2026-10-20

- Images are tagged `arduino-workspace-X.Y.Z` and `arduino-grader-X.Y.Z`. The 1.0.0 workspace keeps its `arduino-1.0.0` tags; update question `info.json` files when upgrading.
- New `arduino-grader-` image for PrairieLearn external grading: it compiles with the workspace toolchain, simulates in simavr on scripted inputs, and runs a question's `tests/test.py`.
- Tests are written with the `arduinograder` package. Compilation and simulation run as an unprivileged user that cannot read `/grade`; simulated time makes results independent of server load.
- `blinkWithoutDelay` autograded template; `scripts/grade.py` grades sketches under production grader limits. `analogWrite()` output is not supported yet.
- Optional helpers in `arduinograder.extras`: `forbid_calls()` and `find_calls()`, and `SevenSegment`, which reads a display's lit segments (A-G and DP, as in Velxio) as a `Segment` set.
- Each question defines which segment shapes count as which digit. Template grader cases are temporary regression tests in `tests/grader/cases/`, outside the question directories.
- Submissions list the extracted `sketch.ino` before `project.vlx`.
- The workspace status bar is removed. The save icon above the file list is the only save control, with a quiet status such as “Saved 5:02 PM” beside it.
- The icon no longer flashes while typing and changes only when a save is overdue or fails. **Source & licenses** moved to the Help menu.
- Changes save 3 s after editing pauses, at least every 30 s while editing and when leaving the workspace; failed saves retry automatically.
- Repository reorganized into `workspace/`, `grader/` and `course/` with one `toolchain.lock.json` and a root `Dockerfile`; the upstream patch is split by topic.
- Tests are in `tests/`, one folder per component; the workspace image test is `tests/workspace/run.sh`.

## 1.0.0 — 2026-09-22

Initial release for PrairieLearn workspaces on Linux AMD64.

- Native Velxio code and circuit editing for one Arduino Uno and `sketch.ino`.
- Offline compilation with the preinstalled Arduino AVR 1.8.6 core.
- Atomic `project.vlx` saves, revision conflict detection and local recovery export.
- Blink and seven-segment question templates with submitted sketch previews for manual grading.
- Container tests for persistence, compilation and Chromium simulation through a PrairieLearn-style proxy.
- Pinned upstream source, dependency locks and a downloadable adapter source archive.

Validation uses a local PrairieLearn-style proxy; it does not include a live PrairieLearn deployment or submission test.
