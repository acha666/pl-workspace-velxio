#!/usr/bin/env python3
"""Exercise the running workspace over nginx, using no external services."""

import copy
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8080"


def request(path, payload=None, method=None, status=200):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        response = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        assert response.status == status, (path, response.status, raw)
        return json.loads(raw) if response.headers.get_content_type() == "application/json" else raw


def main():
    assert os.getuid() == 1001, "Smoke tests must use PrairieLearn's runtime UID"
    for attempt in range(60):
        try:
            request("/health")
            break
        except (OSError, AssertionError):
            if attempt == 59:
                raise
            time.sleep(0.5)

    snapshot = request("/api/pl-workspace")
    project_file = Path("/workspace/project.vlx")
    assert snapshot["revision"] == hashlib.sha256(project_file.read_bytes()).hexdigest()
    assert b"./assets/" in request("/")
    assert b"/pl/workspace/test/container/api" in request("/workspace-config.js")
    request("/api/libraries/install", {}, status=404)
    request("/api/compile/ensure-core", {}, status=404)
    request("/examples", status=404)

    edited = copy.deepcopy(snapshot)
    group = next(iter(edited["project"]["fileGroups"].values()))
    group[0]["content"] += "\n// persistence smoke test\n"
    saved = request("/api/pl-workspace", edited, "PUT")
    assert saved["revision"] != snapshot["revision"]
    assert json.loads(project_file.read_text()) == edited["project"]
    request("/api/pl-workspace", snapshot, "PUT", status=409)
    # Restore the actual starter for browser tests.
    request("/api/pl-workspace", {**snapshot, "revision": saved["revision"]}, "PUT")

    files = [{"name": "sketch.ino", "content": "void setup() {}\nvoid loop() {}\n"}]
    payload = {"files": files, "board_fqbn": "arduino:avr:uno"}
    result = request("/api/compile/", payload)
    assert result["success"], result
    assert result["hex_content"].startswith(":"), result
    failed = request(
        "/api/compile/",
        {**payload, "files": [{**files[0], "content": "#error expected failure"}]},
    )
    assert not failed["success"], failed
    request("/api/compile/", {**payload, "board_fqbn": "esp32:esp32:esp32"}, status=422)
    print(
        "Offline UID 1001: startup, assets, atomic saves, conflicts and AVR compilation passed.",
        flush=True,
    )


if __name__ == "__main__":
    main()
