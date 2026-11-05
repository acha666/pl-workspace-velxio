# Tests

This folder tests the course files. Each grader and workspace image keeps its own tests next to its sources. The Python tests use pytest; those that need a toolchain or the Velxio source run in the Docker target that provides it. See the main [README](../README.md#build-and-test) for the commands.

| Tests                              | Cover                                                                                        | Run by                                  |
| ---------------------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------- |
| `tests/course/`                    | Question templates and `course/serverFilesCourse/velxio.py`                                  | `uv run pytest` at the root             |
| `graders/arduino/tests/`           | `arduinograder` and `avrsim`, and course questions graded end to end with `cases/`; `fake_avrsim.py` replays a scripted `avrsim` so the session protocol is tested without the toolchain | `grader-test` target, or `uv run pytest` in `graders/arduino` |
| `workspaces/arduino/tests/`        | A built workspace image: API in the container, Chromium through a PrairieLearn-style proxy, persistence, shutdown and the source it offers | `bash workspaces/arduino/tests/run.sh IMAGE` |

The workspace adapter's unit tests are copied into the Velxio source, so they stay with the adapter: `workspaces/arduino/adapter/backend/tests/` runs in `backend-test` and `workspaces/arduino/adapter/frontend/src/pl/__tests__/` in `frontend-test`.

`graders/arduino/tests/cases/<path under course/questions/>/` holds sketches for an autograded template and an `expected.json` mapping each to its score, or `null` when it must be ungradable; `grader-test` grades them with pytest, and CI grades them again with `scripts/grade.py --cases` in the built grader image under production limits. Sketches there may solve the templates, since nothing in `tests/` or `graders/` goes into the workspace image or its source archive, which holds the build files and `workspaces/` in full, tests included, with `run.sh` checking that course files and graders stay out.
