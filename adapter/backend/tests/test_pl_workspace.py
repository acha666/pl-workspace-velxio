"""The PL adapter persists native projects without changing the compiler."""

import asyncio
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from app.api.routes import pl_workspace as workspace
from app.services.arduino_cli import ArduinoCLIService


def starter():
    return {
        "format": "velxio-project",
        "version": 1,
        "exportedAt": "2026-09-22T00:00:00.000Z",
        "name": "Button and LED",
        "boards": [
            {
                "id": "uno",
                "boardKind": "arduino-uno",
                "x": 20,
                "y": 30,
                "activeFileGroupId": "group-uno",
                "languageMode": "arduino",
            }
        ],
        "fileGroups": {
            "group-uno": [
                {"name": "sketch.ino", "content": "void setup() {}\nvoid loop() {}\n"}
            ]
        },
        "components": [
            {
                "id": "button",
                "metadataId": "pushbutton",
                "properties": {"color": "green"},
                "x": 300,
                "y": 50,
            }
        ],
        "wires": [
            {
                "id": "wire",
                "start": {"componentId": "uno", "pinName": "2"},
                "end": {"componentId": "button", "pinName": "1.l"},
                "color": "green",
                "waypoints": [],
            }
        ],
        "activeBoardId": "uno",
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "project.vlx").write_text(json.dumps(starter()), encoding="utf-8")
    app = FastAPI()

    @app.post("/api/compile/")
    @app.post("/api/compile/start")
    async def native_compile(request: Request):
        return {"upstream_request": await request.json()}

    @app.get("/api/compile/boards")
    def boards():
        return {"boards": [{"name": "Arduino Uno", "fqbn": "arduino:avr:uno"}]}

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    @app.post("/api/libraries/install")
    def denied():
        raise AssertionError("A blocked endpoint must not execute")

    workspace.register(app)
    with TestClient(app) as test_client:
        yield test_client


def test_round_trip_atomic_native_project(client, tmp_path):
    loaded = client.get("/api/pl-workspace")
    assert loaded.status_code == 200
    assert loaded.headers["cache-control"] == "no-store"
    payload = loaded.json()
    assert payload["project"] == starter()
    assert (
        payload["revision"]
        == hashlib.sha256((tmp_path / "project.vlx").read_bytes()).hexdigest()
    )
    payload["project"]["fileGroups"]["group-uno"][0]["content"] = (
        "// ready ✓\nvoid setup() {}\nvoid loop() {}\n"
    )
    payload["project"]["components"][0]["x"] = 450
    payload["project"]["boards"][0]["futureUpstreamOption"] = {"preserve": True}
    payload["project"]["futureProjectOption"] = ["preserve", 1]
    saved = client.put("/api/pl-workspace", json=payload)
    assert saved.status_code == 200
    disk = json.loads((tmp_path / "project.vlx").read_text())
    assert disk == payload["project"]
    assert (
        saved.json()["revision"]
        == hashlib.sha256((tmp_path / "project.vlx").read_bytes()).hexdigest()
    )
    assert [p.name for p in tmp_path.iterdir()] == ["project.vlx"]
    # Retrying after a lost response confirms the existing write without touching it.
    with patch.object(
        workspace.os, "replace", side_effect=AssertionError("No duplicate write")
    ):
        retried = client.put("/api/pl-workspace", json=payload)
    assert retried.status_code == 200
    assert retried.json() == saved.json()
    payload["project"]["name"] = "A different stale edit"
    assert client.put("/api/pl-workspace", json=payload).status_code == 409
    assert json.loads((tmp_path / "project.vlx").read_text()) == disk


def test_concurrent_tabs_cannot_overwrite_the_same_revision(client, tmp_path):
    loaded = client.get("/api/pl-workspace").json()
    ready = Barrier(2)

    def save(name):
        payload = copy.deepcopy(loaded)
        payload["project"]["name"] = name
        ready.wait(timeout=5)
        response = client.put("/api/pl-workspace", json=payload)
        return name, response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["Tab one", "Tab two"]))
    assert sorted(status for _, status in results) == [200, 409]
    winner = next(name for name, status in results if status == 200)
    assert json.loads((tmp_path / "project.vlx").read_text())["name"] == winner
    assert [p.name for p in tmp_path.iterdir()] == ["project.vlx"]


def test_missing_seed_and_symlinks_fail_without_initialization(client, tmp_path):
    path = tmp_path / "project.vlx"
    payload = client.get("/api/pl-workspace").json()
    path.unlink()
    assert client.get("/api/pl-workspace").status_code == 503
    assert client.put("/api/pl-workspace", json=payload).status_code == 503
    assert not path.exists()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(starter()))
    path.symlink_to(outside)
    assert client.get("/api/pl-workspace").status_code == 503


def test_failed_replace_preserves_last_complete_snapshot(client, tmp_path):
    original = (tmp_path / "project.vlx").read_bytes()
    payload = client.get("/api/pl-workspace").json()
    payload["project"]["name"] = "New name"
    with patch.object(workspace.os, "replace", side_effect=OSError("disk full")):
        response = client.put("/api/pl-workspace", json=payload)
    assert response.status_code == 503
    assert (tmp_path / "project.vlx").read_bytes() == original
    assert [p.name for p in tmp_path.iterdir()] == ["project.vlx"]


@pytest.mark.parametrize(
    "alter",
    [
        lambda p: p.update(format="custom-project"),
        lambda p: p["boards"][0].update(boardKind="esp32"),
        lambda p: p["boards"].append(copy.deepcopy(p["boards"][0])),
        lambda p: p.update(activeBoardId="missing"),
        lambda p: p["fileGroups"]["group-uno"][0].update(name="../sketch.ino"),
        lambda p: p["fileGroups"]["group-uno"].append(
            {"name": "sketch.ino", "content": "extra"}
        ),
        lambda p: p["fileGroups"]["group-uno"][0].update(
            content="x" * (workspace.MAX_CODE_BYTES + 1)
        ),
    ],
)
def test_rejects_unsupported_projects_without_touching_saved_work(
    client, tmp_path, alter
):
    original = (tmp_path / "project.vlx").read_bytes()
    payload = client.get("/api/pl-workspace").json()
    alter(payload["project"])
    assert client.put("/api/pl-workspace", json=payload).status_code == 422
    assert (tmp_path / "project.vlx").read_bytes() == original


def test_runtime_api_gate_and_compile_passthrough(client):
    compile_request = {
        "files": [
            {"name": "sketch.ino", "content": "void setup() {}\nvoid loop() {}\n"}
        ],
        "board_fqbn": "arduino:avr:uno",
        "board_kind": "arduino-uno",
        "language": "arduino",
        "libraries": [],
    }
    for endpoint in ["/api/compile/", "/api/compile/start"]:
        response = client.post(endpoint, json=compile_request)
        assert response.status_code == 200
        assert response.json()["upstream_request"] == compile_request
        invalid = {**compile_request, "board_fqbn": "esp32:esp32:esp32"}
        assert client.post(endpoint, json=invalid).status_code == 422
        assert (
            client.post(endpoint, json={**compile_request, "language": {}}).status_code
            == 422
        )
    assert client.get("/api/compile/boards").status_code == 200
    assert client.get("/health").status_code == 200
    for endpoint in [
        "/api/libraries/install",
        "/api/compile/ensure-core",
        "/api/gateway",
        "/api/flash",
    ]:
        assert client.post(endpoint, json={}).status_code == 404
    assert client.get("/api/docs").status_code == 404


def test_json_size_and_cross_site_writes(client):
    payload = client.get("/api/pl-workspace").json()
    assert (
        client.put(
            "/api/pl-workspace", json=payload, headers={"Sec-Fetch-Site": "cross-site"}
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/pl-workspace",
            content=json.dumps(payload),
            headers={"Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert (
        client.put(
            "/api/pl-workspace",
            content=b" " * (workspace.MAX_PROJECT_BYTES + 1),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    # The proxy may rewrite Host; do not incorrectly reject its public Origin.
    assert (
        client.put(
            "/api/pl-workspace",
            json=payload,
            headers={
                "Origin": "https://workspace.example",
                "Sec-Fetch-Site": "same-origin",
            },
        ).status_code
        == 200
    )


def test_pl_cli_initialization_never_updates_or_installs(monkeypatch):
    monkeypatch.setenv("VELXIO_PL_WORKSPACE", "1")
    with (
        patch.object(ArduinoCLIService, "_ensure_board_urls") as urls,
        patch.object(ArduinoCLIService, "_ensure_core_installed") as cores,
    ):
        service = ArduinoCLIService()
    urls.assert_not_called()
    cores.assert_not_called()
    with patch(
        "app.services.arduino_cli.subprocess.run",
        side_effect=AssertionError("No runtime install/list command"),
    ):
        assert (
            asyncio.run(service.ensure_core_for_board("arduino:avr:uno"))["installed"]
            is True
        )
        assert (
            asyncio.run(service.ensure_core_for_board("esp32:esp32:esp32"))["installed"]
            is False
        )
        assert asyncio.run(service.list_boards()) == [
            {"name": "Arduino Uno", "fqbn": "arduino:avr:uno"}
        ]


def test_normal_cli_keeps_upstream_initialization(monkeypatch):
    monkeypatch.delenv("VELXIO_PL_WORKSPACE", raising=False)
    with (
        patch.object(ArduinoCLIService, "_ensure_board_urls") as urls,
        patch.object(ArduinoCLIService, "_ensure_core_installed") as cores,
    ):
        ArduinoCLIService()
    urls.assert_called_once()
    cores.assert_called_once()
