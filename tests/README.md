# Tests

Each folder tests one part of the repository. The Python tests use pytest and run in the Docker target that provides what they need; see the main [README](../README.md#build-and-test) for the commands.

| Folder       | Tests                                                                                        | Run by                                  |
| ------------ | -------------------------------------------------------------------------------------------- | --------------------------------------- |
| `scripts/`   | `scripts/prepare.py`                                                                         | `backend-test` target                   |
| `course/`    | Question templates and `course/serverFilesCourse/velxio.py`                                  | `backend-test` target                   |
| `grader/`    | `arduinograder` and `avrsim`, and course questions graded end to end with `cases/`           | `grader-test` target                    |
| `workspace/` | A built workspace image: API in the container, Chromium through a PrairieLearn-style proxy, persistence and shutdown | `bash tests/workspace/run.sh IMAGE` |

The workspace adapter's unit tests are copied into the Velxio source, so they stay with the adapter: `workspace/adapter/backend/tests/` runs in `backend-test` and `workspace/adapter/frontend/src/pl/__tests__/` in `frontend-test`.

`grader/cases/<path under course/questions/>/` holds sketches for an autograded template and an `expected.json` mapping each to its score, or `null` when it must be ungradable. `grader-test` grades them with pytest, and CI grades them again with `scripts/grade.py --cases` in the built grader image under production limits.

Nothing in `tests/` goes into the workspace image or its source archive, so sketches here may solve the templates. Keep solutions out of `workspace/` and `scripts/`.
