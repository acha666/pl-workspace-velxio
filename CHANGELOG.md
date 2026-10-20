# Changelog

## Unreleased (1.1.0)

- Images are tagged `arduino-workspace-X.Y.Z` and `arduino-grader-X.Y.Z`. The 1.0.0 workspace keeps its `arduino-1.0.0` tags; update question `info.json` files when upgrading.
- New `arduino-grader-` image for PrairieLearn external grading: compiles with the workspace toolchain, simulates in simavr on scripted inputs, and runs a question's `tests/test.py` written with the `arduinograder` package.
- Compilation and simulation run as an unprivileged user that cannot read `/grade`; simulated time makes results independent of server load.
- `blinkWithoutDelay` autograded template with grader cases; `scripts/grade.py` checks cases under production grader limits.
- Repository reorganized into `workspace/`, `grader/` and `course/` with one `toolchain.lock.json`; the workspace image is unchanged apart from layer order.

## 1.0.0 — 2026-09-22

Initial release for PrairieLearn workspaces on Linux AMD64.

- Native Velxio code and circuit editing for one Arduino Uno and `sketch.ino`.
- Offline compilation with the preinstalled Arduino AVR 1.8.6 core.
- Atomic `project.vlx` saves, revision conflict detection and local recovery export.
- Blink and seven-segment question templates with submitted sketch previews for manual grading.
- Container tests for persistence, compilation and Chromium simulation through a PrairieLearn-style proxy.
- Pinned upstream source, dependency locks and a downloadable adapter source archive.

Validation uses a local PrairieLearn-style proxy; it does not include a live PrairieLearn deployment or submission test.
