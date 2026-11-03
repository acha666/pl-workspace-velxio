# PrairieLearn Velxio workspace and Arduino grader

[![GitHub](https://img.shields.io/badge/GitHub-acha666%2Fpl--workspace--velxio-181717?logo=github)](https://github.com/acha666/pl-workspace-velxio)
[![Docker Hub](https://img.shields.io/badge/Docker_Hub-acha666%2Fpl--workspace--velxio-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/acha666/pl-workspace-velxio)

Arduino Uno code and circuit editing in [PrairieLearn Workspace](https://docs.prairielearn.com/workspaces/), powered by [Velxio](https://github.com/davidmonterocrespo24/velxio), and an external grader that compiles and simulates the submitted sketch.

Both images are built from one pinned toolchain, so students and the grader compile with the same Arduino CLI and AVR core.

| Image tag                                             | Use in `info.json`       | Contents                                                     |
| ----------------------------------------------------- | ------------------------ | ------------------------------------------------------------ |
| `acha666/pl-workspace-velxio:arduino-workspace-X.Y.Z` | `workspaceOptions.image` | Velxio editor and simulator, offline compilation             |
| `acha666/pl-workspace-velxio:arduino-grader-X.Y.Z`    | `externalGradingOptions` | Arduino CLI, [simavr](https://github.com/buserror/simavr) runner and the `arduinograder` Python package |

Use the same version for both images in a question.

## Teacher quick start

1. Copy `course/questions/arduino/` into your course's `questions/` directory and `course/serverFilesCourse/velxio.py` into `serverFilesCourse/`.
2. Add the questions to an assessment, for example `{"id":"arduino/blink","manualPoints":10}` or `{"id":"arduino/blinkWithoutDelay","autoPoints":10}`. Generate a new question UUID when making additional copies.
3. Open each workspace in PrairieLearn and try an edit, Run, reload and submission before assigning it.

The workspace saves automatically; once the save icon above its file list is green, students return to PrairieLearn and save or grade the question. Submissions include the complete `project.vlx` and a `sketch.ino` extracted from that snapshot, which manual grading and the grader use.

Edit each question's prompt and `workspace/project.vlx` to customize it. Each workspace supports one Arduino Uno and one `sketch.ino`. Only core-provided libraries are available; the AVR core is preinstalled for offline compilation.

`blinkWithoutDelay` and `modeSwitch` are autograded examples whose `tests/test.py` defines the tests; `modeSwitch` reacts to the running sketch with button presses, serial input and a potentiometer. See the [grader guide](graders/arduino/README.md) to write tests and to check them locally with `scripts/grade.py`. The grader does not support `analogWrite()` output yet.

## Repository layout

| Path                   | Contents                                                                        |
| ---------------------- | ------------------------------------------------------------------------------- |
| `Dockerfile`           | Every version pin (Velxio commit and image, AVR core, simavr commit), the shared `toolchain` stage and the `workspace` and `grader` targets with their tests |
| `docker-bake.hcl`      | The image and test targets for `docker buildx bake`, used locally and in CI      |
| `pyproject.toml`, `uv.lock` | The [uv](https://docs.astral.sh/uv/) workspace: every grader under `graders/` is a member, with one lock file and shared lint settings |
| `workspaces/arduino/`  | The Arduino workspace image: Velxio adapter, upstream patches, dependency locks, nginx, entrypoint and its image test |
| `graders/arduino/`     | The Arduino grader: `avrsim` simavr runner, the `arduinograder` package (`src/`) and its tests |
| `course/`              | Files to copy into a course: question templates and `velxio.py`                 |
| `scripts/`             | `grade.py` for grading sketches                                                 |
| `tests/`               | Tests for the course templates; see [tests](tests/README.md)                    |

Further graders go in `graders/<name>/` as workspace members and further workspace images in `workspaces/<name>/`, each with its own Dockerfile and bake targets.

## Build and test

Requires Docker with Buildx and Python 3.12+. Builds download dependencies; running workspaces and grading need no internet access.

```sh
docker buildx bake test
docker buildx bake --load
bash workspaces/arduino/tests/run.sh pl-arduino-workspace:dev
python3 scripts/grade.py --image pl-arduino-grader:dev --cases graders/arduino/tests/cases/arduino/blinkWithoutDelay course/questions/arduino/blinkWithoutDelay
```

`docker buildx bake test` runs the frontend, backend and grader test targets in parallel, and `docker buildx bake --load` builds and loads `pl-arduino-workspace:dev` and `pl-arduino-grader:dev`. Name a target to build only that one, for example `docker buildx bake arduino-grader-test`; CI builds the same targets. The Dockerfile fetches the pinned Velxio commit and applies the patches, adapter and dependency locks itself; to try changes in a local Velxio checkout of that commit, pass `--set '*.contexts.velxio-upstream=PATH'` to bake. Tests run in containers and cover saves, compilation, templates and Chromium through a PrairieLearn-style proxy, the source the workspace offers, the grader package, and the template cases under production grader limits.

The Python code is developed with [uv](https://docs.astral.sh/uv/): `uv sync --all-packages` at the root creates one environment for every grader and the course tests. There, `uv run ruff check .` and `uv run ruff format --check .` lint the repository and `uv run pytest` tests the course templates; in `graders/arduino`, `uv run mypy` and `uv run pytest` type-check and test the grader. Tests that compile or simulate are skipped unless `arduino-cli` and `avrsim` are installed, so run `docker buildx bake arduino-grader-test` for the full suite; `grader-test` runs the same lint, type and test commands. CI runs these checks first and builds the images only when they pass.

## Docker Hub releases

Stable Git tags such as `v2.0.0` run all container tests before publishing `arduino-workspace-2.0.0`, `arduino-workspace-2.0`, `arduino-workspace-2` and `arduino-workspace`, and the matching `arduino-grader-` tags, to Docker Hub. Release 1.0.0 was published only as `arduino-1.0.0` and its `arduino-` aliases.

Before tagging, update the [changelog](CHANGELOG.md) and template image versions, run the checks above, then commit and push the release commit and tag. Confirm the tag workflow succeeds and the versioned images are available before using them in a course.

Update the pins at the top of the Dockerfile and `workspaces/arduino/dependencies/` together, review patch conflicts and rerun all tests when upgrading. [Source and license](SOURCE.md).
