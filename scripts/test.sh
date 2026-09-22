#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
image=${1:-pl-workspace-velxio:test}
container=
volume=
cleanup() {
    if [[ -n "$container" ]]; then
        docker logs "$container" >&2
        docker rm -f "$container" >/dev/null
    fi
    if [[ -n "$volume" ]]; then
        docker volume rm "$volume" >/dev/null
    fi
}
trap cleanup EXIT

create_workspace() {
    docker create --network none \
        --mount "type=volume,src=$volume,dst=/workspace" \
        -e WORKSPACE_BASE_URL=/pl/workspace/test/container/ "$image"
}

docker build -t pl-workspace-velxio:browser-tests tests/browser
for template in blink sevenSegment; do
    volume=$(docker volume create)
    container=$(create_workspace)
    docker cp "templates/questions/arduino/$template/workspace/project.vlx" "$container:/workspace/project.vlx"
    docker cp scripts/smoke.py "$container:/tmp/smoke.py"
    docker start "$container" >/dev/null
    docker exec "$container" python /tmp/smoke.py
    docker run --rm --init --network "container:$container" --shm-size=512m \
        --mount "type=bind,src=$PWD,dst=/repo,readonly" \
        pl-workspace-velxio:browser-tests node smoke.mjs "$template"
    before=$(docker exec "$container" sha256sum /workspace/project.vlx)
    docker stop --time 5 "$container" >/dev/null
    test "$(docker inspect --format '{{.State.ExitCode}}' "$container")" = 143
    docker rm "$container" >/dev/null
    container=$(create_workspace)
    docker cp scripts/smoke.py "$container:/tmp/smoke.py"
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
