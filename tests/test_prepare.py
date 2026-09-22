"""Build preparation must work inside a checkout and from distributed source."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest


PREPARE = Path(__file__).resolve().parents[1] / "scripts/prepare.py"
spec = importlib.util.spec_from_file_location("prepare", PREPARE)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args])


@pytest.fixture
def project(tmp_path, monkeypatch):
    upstream = tmp_path / "upstream"
    (upstream / "frontend").mkdir(parents=True)
    (upstream / "backend").mkdir()
    (upstream / "backend/requirements.txt").write_text("fastapi\n")
    tracked = upstream / "frontend/example.txt"
    tracked.write_text("Original upstream file.\n")
    git(upstream, "init", "--quiet")
    git(upstream, "add", ".")
    git(
        upstream,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Fixture",
    )
    commit = git(upstream, "rev-parse", "HEAD").decode().strip()
    tracked.write_text("PrairieLearn patch applied.\n")
    patch = git(upstream, "diff")
    tracked.write_text("Uncommitted local changes must stay private.\n")
    (upstream / "private.txt").write_text("Untracked files must stay private.\n")

    # Reproduce git apply's silent path skipping when its cwd is below an
    # enclosing repository rather than at that repository's root.
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "--quiet")
    root = repository / "nested workspace"
    for directory in [
        "patches",
        "adapter/frontend",
        "dependencies",
        "docker",
        "scripts",
        "tests",
        "templates",
    ]:
        (root / directory).mkdir(parents=True)
    (root / "patches/workspace.patch").write_bytes(patch)
    (root / "adapter/frontend/workspace.ts").write_text(
        "export const workspace = true;\n"
    )
    (root / "dependencies/frontend-package-lock.json").write_text("{}\n")
    (root / "dependencies/backend-constraints.txt").write_text("fastapi==0.135.1\n")
    (root / "docker/Dockerfile").write_text(
        "ARG VELXIO_BASE_IMAGE=example/runtime@sha256:123\n"
        "RUN arduino-cli core install arduino:avr@1.8.6\n"
    )
    shutil.copy2(PREPARE, root / "scripts/prepare.py")
    for name in ["LICENSE", "SOURCE.md", "tests/answer.txt", "templates/answer.txt"]:
        (root / name).write_text(name + "\n")
    (root / "upstream.lock.json").write_text(
        json.dumps(
            {
                "repository": str(upstream),
                "commit": commit,
                "image": "example/runtime@sha256:123",
                "arduino_avr_core": "1.8.6",
            }
        )
    )
    monkeypatch.setattr(prepare, "ROOT", root)
    return root, upstream


def run_prepare(monkeypatch, upstream, output):
    monkeypatch.setattr(
        sys,
        "argv",
        [str(PREPARE), "--local-upstream", str(upstream), "--output", str(output)],
    )
    prepare.main()


def test_nested_checkout_applies_patch_and_distributed_source_rebuilds(
    project, monkeypatch
):
    root, upstream = project
    output = root / ".build"
    run_prepare(monkeypatch, upstream, output)

    assert (
        output / "upstream/frontend/example.txt"
    ).read_text() == "PrairieLearn patch applied.\n"
    assert (output / "upstream/frontend/workspace.ts").is_file()
    assert (output / "upstream/frontend/package-lock.json").read_text() == "{}\n"
    assert (
        output / "upstream/backend/constraints.txt"
    ).read_text() == "fastapi==0.135.1\n"
    assert not (output / "upstream/private.txt").exists()
    assert not (output / "upstream/.git").exists()
    assert (upstream / "frontend/example.txt").read_text().startswith("Uncommitted")

    distributed = root / "distributed-source"
    with tarfile.open(output / "pl-adapter-source.tar.gz") as archive:
        names = archive.getnames()
        assert not any(name.split("/")[0] in {"tests", "templates"} for name in names)
        archive.extractall(distributed, filter="data")
    monkeypatch.setattr(prepare, "ROOT", distributed)
    rebuilt = distributed / ".build"
    run_prepare(monkeypatch, upstream, rebuilt)
    assert (
        rebuilt / "upstream/frontend/example.txt"
    ).read_text() == "PrairieLearn patch applied.\n"
    assert (rebuilt / "upstream/frontend/workspace.ts").is_file()
    assert list((rebuilt / "tests").iterdir()) == []
    assert list((rebuilt / "templates").iterdir()) == []


def test_failed_patch_leaves_no_output(project, monkeypatch):
    root, upstream = project
    (root / "patches/workspace.patch").write_text("Not a patch.\n")
    output = root / ".build"
    with pytest.raises(subprocess.CalledProcessError):
        run_prepare(monkeypatch, upstream, output)
    assert not output.exists()


def test_failed_publish_leaves_no_output(project, monkeypatch):
    root, upstream = project
    output = root / ".build"

    def fail_copy(source, destination):
        destination.mkdir()
        (destination / "partial.txt").write_text("Incomplete copy.\n")
        raise OSError("Simulated cross-device copy failure")

    monkeypatch.setattr(prepare.shutil, "move", fail_copy)
    with pytest.raises(OSError, match="Simulated"):
        run_prepare(monkeypatch, upstream, output)
    assert not output.exists()
    assert not list(root.glob("..build-*"))


def test_existing_output_is_preserved(project, monkeypatch):
    root, upstream = project
    output = root / ".build"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("Keep this build.\n")
    with pytest.raises(SystemExit):
        run_prepare(monkeypatch, upstream, output)
    assert marker.read_text() == "Keep this build.\n"


@pytest.mark.parametrize(
    "field,value",
    [
        ("image", "example/changed@sha256:456"),
        ("arduino_avr_core", "0.0.0"),
        ("commit", "0" * 40),
    ],
)
def test_lock_drift_is_rejected(project, monkeypatch, field, value):
    root, upstream = project
    lock_path = root / "upstream.lock.json"
    lock = json.loads(lock_path.read_text())
    lock[field] = value
    lock_path.write_text(json.dumps(lock))
    output = root / ".build"
    with pytest.raises(SystemExit):
        run_prepare(monkeypatch, upstream, output)
    assert not output.exists()
