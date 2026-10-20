# PrairieLearn Velxio workspace and Arduino grader

Arduino Uno code and circuit editing in [PrairieLearn Workspace](https://docs.prairielearn.com/workspaces/), powered by [Velxio](https://github.com/davidmonterocrespo24/velxio), and an external grader that compiles and simulates the submitted sketch. [GitHub](https://github.com/acha666/pl-workspace-velxio) · [Docker Hub](https://hub.docker.com/r/acha666/pl-workspace-velxio).

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

Students wait for **Saved to workspace**, then return to PrairieLearn and save or grade the question. Submissions include the complete `project.vlx` and a `sketch.ino` extracted from that snapshot, which manual grading and the grader use.

Edit each question's prompt and `workspace/project.vlx` to customize it. Each workspace supports one Arduino Uno and one `sketch.ino`. Only core-provided libraries are available; the AVR core is preinstalled for offline compilation.

`blinkWithoutDelay` is an autograded example: its `tests/test.py` defines the tests, and `grader-cases/` holds sketches with their expected scores. See the [grader guide](grader/README.md) to write tests and to check them locally with `scripts/grade.py`.

## Repository layout

| Path                   | Contents                                                                        |
| ---------------------- | ------------------------------------------------------------------------------- |
| `toolchain.lock.json`  | Velxio revision and image, AVR core and simavr commit; checked against the Dockerfile |
| `docker/Dockerfile`    | Shared `toolchain` stage and the `workspace` and `grader` targets with their tests |
| `workspace/`           | Velxio adapter, upstream patches, dependency locks, nginx and entrypoint         |
| `grader/`              | `avrsim` simavr runner, `arduinograder` package and its tests                    |
| `course/`              | Files to copy into a course: question templates and `velxio.py`                 |
| `scripts/`             | Build preparation, workspace browser tests and `grade.py`                       |
| `tests/`               | Build preparation and course template tests                                     |

## Build and test

Requires Docker, Git and Python 3.12+. Builds download dependencies; running workspaces and grading need no internet access.

```sh
python3 scripts/prepare.py
docker build --target frontend-test -f docker/Dockerfile .build
docker build --target backend-test -f docker/Dockerfile .build
docker build --target grader-test -f docker/Dockerfile .build
docker build --platform linux/amd64 --target workspace -f docker/Dockerfile -t pl-workspace-velxio:arduino .build
docker build --platform linux/amd64 --target grader -f docker/Dockerfile -t pl-arduino-grader .build
bash scripts/test-workspace.sh pl-workspace-velxio:arduino
python3 scripts/grade.py --image pl-arduino-grader course/questions/arduino/blinkWithoutDelay
```

Use a fresh `--output` directory when preparing again. Tests run in containers and cover saves, compilation, templates and Chromium through a PrairieLearn-style proxy, the grader package, and each autograded template's cases under production grader limits. The grader targets also build from the repository root (`docker build --target grader -f docker/Dockerfile .`), which is quicker while working on the grader.

## Docker Hub releases

Stable Git tags such as `v1.1.0` run all container tests before publishing `arduino-workspace-1.1.0`, `arduino-workspace-1.1`, `arduino-workspace-1` and `arduino-workspace`, and the matching `arduino-grader-` tags, to Docker Hub. Release 1.0.0 was published only as `arduino-1.0.0` and its `arduino-` aliases. The repository requires Actions variables `DOCKERHUB_IMAGE` and `DOCKERHUB_USERNAME`, plus the `DOCKERHUB_TOKEN` secret. Branch and pull-request builds test without publishing.

Before tagging, update the [changelog](CHANGELOG.md) and template image versions, run the checks above, then commit and push the release commit and tag. Confirm the tag workflow succeeds and the versioned images are available before using them in a course.

Update the pins in `toolchain.lock.json`, the Dockerfile and `workspace/dependencies/` together, review patch conflicts and rerun all tests when upgrading. [Source and license](SOURCE.md).
