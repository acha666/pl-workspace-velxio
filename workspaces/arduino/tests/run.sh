#!/bin/bash
# Test a built workspace image with each template: the API smoke test inside
# the container, Chromium through a PrairieLearn-style proxy, persistence
# across container replacement and clean shutdown. Then check the source the
# image offers: no course files or graders, and the image rebuilds from it.
set -euo pipefail
cd "$(dirname "$0")/../../.."
image=${1:-pl-arduino-workspace:dev}
container=
volume=
offer=
cleanup() {
    if [[ -n "$container" ]]; then
        docker logs "$container" >&2
        docker rm -f "$container" >/dev/null
    fi
    if [[ -n "$volume" ]]; then
        docker volume rm "$volume" >/dev/null
    fi
    if [[ -n "$offer" ]]; then
        rm -rf "$offer"
    fi
}
trap cleanup EXIT

create_workspace() {
    docker create --network none \
        --mount "type=volume,src=$volume,dst=/workspace" \
        -e WORKSPACE_BASE_URL=/pl/workspace/test/container/ "$image"
}

docker build -t pl-workspace-velxio:browser-tests workspaces/arduino/tests/browser
for template in blink sevenSegment; do
    volume=$(docker volume create)
    container=$(create_workspace)
    docker cp "course/questions/arduino/$template/workspace/project.vlx" "$container:/workspace/project.vlx"
    docker cp workspaces/arduino/tests/smoke.py "$container:/tmp/smoke.py"
    docker start "$container" >/dev/null
    docker exec "$container" python /tmp/smoke.py
    docker run --rm --init --network "container:$container" --shm-size=512m \
        pl-workspace-velxio:browser-tests node smoke.mjs "$template"
    before=$(docker exec "$container" sha256sum /workspace/project.vlx)
    docker stop --time 5 "$container" >/dev/null
    test "$(docker inspect --format '{{.State.ExitCode}}' "$container")" = 143
    docker rm "$container" >/dev/null
    container=$(create_workspace)
    docker cp workspaces/arduino/tests/smoke.py "$container:/tmp/smoke.py"
    docker start "$container" >/dev/null
    after=$(docker exec "$container" sha256sum /workspace/project.vlx)
    test "$before" = "$after"
    # A replacement container must load and compile the persisted project.
    docker exec "$container" python /tmp/smoke.py
    docker stop --time 5 "$container" >/dev/null
    test "$(docker inspect --format '{{.State.ExitCode}}' "$container")" = 143
    docker rm "$container" >/dev/null
    container=
    docker volume rm "$volume" >/dev/null
    volume=
    echo "$template: browser, container replacement persistence and shutdown passed."
done

offer=$(mktemp -d)
docker run --rm --network none --entrypoint cat "$image" \
    /usr/share/nginx/html/pl-adapter-source.tar.gz | tar -xz -C "$offer"
test -f "$offer/Dockerfile"
for path in course graders tests scripts; do
    test ! -e "$offer/$path"
done
# Matching files hit the build cache, so this is quick after building the image.
docker buildx build --quiet --platform linux/amd64 --target workspace \
    --output type=cacheonly "$offer" >/dev/null
echo "Source offer: no course files or graders, and the workspace rebuilds from it."
