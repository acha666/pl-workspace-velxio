# Tests

This folder tests the repository-level scripts, course files and grader. Each workspace image keeps its own tests next to its sources. The Python tests use pytest and run in the Docker target that provides what they need; see the main [README](../README.md#build-and-test) for the commands.

| Tests                              | Cover                                                                                        | Run by                                  |
| ---------------------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------- |
| `tests/scripts/`                   | `scripts/prepare.py`                                                                         | `backend-test` target                   |
| `tests/course/`                    | Question templates and `course/serverFilesCourse/velxio.py`                                  | `backend-test` target                   |
| `tests/grader/`                    | `arduinograder` and `avrsim`, and course questions graded end to end with `cases/`           | `grader-test` target                    |
| `workspaces/arduino/tests/`        | A built workspace image: API in the container, Chromium through a PrairieLearn-style proxy, persistence and shutdown | `bash workspaces/arduino/tests/run.sh IMAGE` |

The workspace adapter's unit tests are copied into the Velxio source, so they stay with the adapter: `workspaces/arduino/adapter/backend/tests/` runs in `backend-test` and `workspaces/arduino/adapter/frontend/src/pl/__tests__/` in `frontend-test`.

`tests/grader/cases/<path under course/questions/>/` holds sketches for an autograded template and an `expected.json` mapping each to its score, or `null` when it must be ungradable. `grader-test` grades them with pytest, and CI grades them again with `scripts/grade.py --cases` in the built grader image under production limits.

Nothing in `tests/` goes into the workspace image or its source archive, so sketches here may solve the templates. `workspaces/` and `scripts/` go into the archive in full, tests included.
