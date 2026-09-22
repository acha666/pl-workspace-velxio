# PrairieLearn Velxio workspace

Arduino Uno code and circuit editing in [PrairieLearn Workspace](https://docs.prairielearn.com/workspaces/), powered by [Velxio](https://github.com/davidmonterocrespo24/velxio). [GitHub](https://github.com/acha666/pl-workspace-velxio) · [Docker Hub](https://hub.docker.com/r/acha666/pl-workspace-velxio).

## Teacher quick start

1. Copy `templates/questions/arduino/` into your course's `questions/` directory and `templates/serverFilesCourse/velxio.py` into `serverFilesCourse/`.
2. Add both questions to an assessment, for example `{"id":"arduino/blink","manualPoints":10}`. Generate a new question UUID when making additional copies.
3. Open each workspace in PrairieLearn and try an edit, Run, reload and submission before assigning it.

Students wait for **Saved to workspace**, then return to PrairieLearn and click **Save** to submit. Manual grading includes the complete `project.vlx` and a `sketch.ino` preview extracted from that submission.

Templates use `acha666/pl-workspace-velxio:arduino-1.0.0` (Linux AMD64). Use a published version tag or digest in each question's `info.json`.

Edit each question's prompt and `workspace/project.vlx` to customize it. Each workspace supports one Arduino Uno and one `sketch.ino`. Only core-provided libraries are available; the AVR core is preinstalled for offline compilation.

## Build and test

Requires Docker, Git and Python 3.12+. Builds download dependencies; running workspaces needs no internet access.

```sh
python3 scripts/prepare.py
docker build --platform linux/amd64 -f docker/Dockerfile -t pl-workspace-velxio:arduino .build
docker build --target frontend-test -f docker/Dockerfile .build
docker build --target backend-test -f docker/Dockerfile .build
bash scripts/test.sh pl-workspace-velxio:arduino
```

Use a fresh `--output` directory when preparing again. Tests run in containers and cover saves, compilation, templates and Chromium through a PrairieLearn-style proxy.

## Docker Hub releases

Stable Git tags such as `v1.0.0` run all container tests before publishing `arduino-1.0.0`, `arduino-1.0`, `arduino-1` and `arduino` to Docker Hub. The repository requires Actions variables `DOCKERHUB_IMAGE` and `DOCKERHUB_USERNAME`, plus the `DOCKERHUB_TOKEN` secret. Branch and pull-request builds test without publishing.

Before tagging, update the [changelog](CHANGELOG.md) and template image versions, run the checks above, then commit and push the release commit and tag. Confirm the tag workflow succeeds and the versioned image is available before using it in a course.

Source pins and dependency locks are in `upstream.lock.json` and `dependencies/`. `adapter/` contains the workspace integration; `patches/` connects it to upstream. Update the pins together, review patch conflicts and rerun tests when upgrading. [Source and license](SOURCE.md).
