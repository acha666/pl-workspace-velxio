# Changelog

## 1.0.0 — 2026-09-22

Initial release for PrairieLearn workspaces on Linux AMD64.

- Native Velxio code and circuit editing for one Arduino Uno and `sketch.ino`.
- Offline compilation with the preinstalled Arduino AVR 1.8.6 core.
- Atomic `project.vlx` saves, revision conflict detection and local recovery export.
- Blink and seven-segment question templates with submitted sketch previews for manual grading.
- Container tests for persistence, compilation and Chromium simulation through a PrairieLearn-style proxy.
- Pinned upstream source, dependency locks and a downloadable adapter source archive.

Validation uses a local PrairieLearn-style proxy; it does not include a live PrairieLearn deployment or submission test.
