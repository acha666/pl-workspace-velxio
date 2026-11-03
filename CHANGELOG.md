# Changelog

## Unreleased

The workspace image is unchanged apart from where its sources live.

### Repository

- The Arduino workspace sources are in `workspaces/arduino/`, with the workspace image test beside them; `tests/` keeps the script, course template and grader tests.

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
