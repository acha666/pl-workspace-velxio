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

`blinkWithoutDelay` is an autograded example whose `tests/test.py` defines the tests. See the [grader guide](grader/README.md) to write tests and to check them locally with `scripts/grade.py`. The grader does not support `analogWrite()` output yet.

## Repository layout

| Path                   | Contents                                                                        |
| ---------------------- | ------------------------------------------------------------------------------- |
| `toolchain.lock.json`  | Velxio revision and image, AVR core and simavr commit; checked against the Dockerfile |
| `Dockerfile`           | Shared `toolchain` stage and the `workspace` and `grader` targets with their tests |
| `workspace/`           | Velxio adapter, upstream patches, dependency locks, nginx and entrypoint         |
| `grader/`              | `avrsim` simavr runner and the `arduinograder` package                           |
| `course/`              | Files to copy into a course: question templates and `velxio.py`                 |
| `scripts/`             | `prepare.py` for the build context and `grade.py` for grading sketches          |
| `tests/`               | Tests for the scripts, course templates, grader and workspace image; see [tests](tests/README.md) |

## Build and test

Requires Docker, Git and Python 3.12+. Builds download dependencies; running workspaces and grading need no internet access.

```sh
python3 scripts/prepare.py
docker build --target frontend-test .build
docker build --target backend-test .build
docker build --target grader-test .build
docker build --platform linux/amd64 --target workspace -t pl-workspace-velxio:arduino .build
docker build --platform linux/amd64 --target grader -t pl-arduino-grader .build
bash tests/workspace/run.sh pl-workspace-velxio:arduino
python3 scripts/grade.py --image pl-arduino-grader --cases tests/grader/cases/arduino/blinkWithoutDelay course/questions/arduino/blinkWithoutDelay
```

Use a fresh `--output` directory when preparing again. Tests run in containers and cover saves, compilation, templates and Chromium through a PrairieLearn-style proxy, the grader package, and the template cases under production grader limits. The grader targets also build from the repository root (`docker build --target grader .`), which is quicker while working on the grader.

## Docker Hub releases

Stable Git tags such as `v1.1.0` run all container tests before publishing `arduino-workspace-1.1.0`, `arduino-workspace-1.1`, `arduino-workspace-1` and `arduino-workspace`, and the matching `arduino-grader-` tags, to Docker Hub. Release 1.0.0 was published only as `arduino-1.0.0` and its `arduino-` aliases.

Before tagging, update the [changelog](CHANGELOG.md) and template image versions, run the checks above, then commit and push the release commit and tag. Confirm the tag workflow succeeds and the versioned images are available before using them in a course.

Update the pins in `toolchain.lock.json`, the Dockerfile and `workspace/dependencies/` together, review patch conflicts and rerun all tests when upgrading. [Source and license](SOURCE.md).
