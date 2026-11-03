#!/usr/bin/env python3
"""Prepare a pinned upstream checkout and the Docker build context for both images."""

import argparse
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE
    ).stdout


def validate_runtime(lock):
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    image = re.search(r"^ARG VELXIO_BASE_IMAGE=(\S+)$", dockerfile, re.MULTILINE)
    core = re.search(r"arduino-cli core install arduino:avr@(\S+)", dockerfile)
    simavr = re.search(r"^ARG SIMAVR_COMMIT=(\S+)$", dockerfile, re.MULTILINE)
    if image is None or image.group(1) != lock["image"]:
        raise SystemExit("Dockerfile base image does not match toolchain.lock.json.")
    if core is None or core.group(1) != lock["arduino_avr_core"]:
        raise SystemExit("Dockerfile Arduino core does not match toolchain.lock.json.")
    if simavr is None or simavr.group(1) != lock["simavr_commit"]:
        raise SystemExit("Dockerfile simavr commit does not match toolchain.lock.json.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".build")
    parser.add_argument(
        "--local-upstream",
        type=Path,
        help="Use a local checkout at the locked commit instead of fetching it.",
    )
    args = parser.parse_args()
    lock = json.loads((ROOT / "toolchain.lock.json").read_text())
    validate_runtime(lock)
    patches = sorted((ROOT / "workspaces/arduino/patches").glob("*.patch"))
    if not patches:
        parser.error("No PL adapter patch was found.")
    output = args.output.resolve()
    if output.exists():
        parser.error(f"{output} already exists; select a new --output directory.")

    with tempfile.TemporaryDirectory(prefix="velxio-source-") as temporary:
        checkout = args.local_upstream
        if checkout is None:
            checkout = Path(temporary) / "upstream"
            checkout.mkdir()
            git("init", "--quiet", str(checkout))
            git("remote", "add", "origin", lock["repository"], cwd=checkout)
            git("fetch", "--depth=1", "origin", lock["commit"], cwd=checkout)
            git("checkout", "--quiet", "--detach", "FETCH_HEAD", cwd=checkout)
        actual = git("rev-parse", "HEAD", cwd=checkout).decode().strip()
        if actual != lock["commit"]:
            raise SystemExit(f"Expected upstream {lock['commit']}; found {actual}.")
        # Archive only tracked source; never copy a user's node_modules, local
        # credentials, modified working files or .git directory into the image.
        archive = git("archive", "--format=tar", "HEAD", cwd=checkout)
        # Apply outside the caller's Git repository: git apply can otherwise
        # silently skip paths when run in an untracked subdirectory.
        context = Path(temporary) / "context"
        source = context / "upstream"
        source.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(source, filter="data")
        for patch in patches:
            git("apply", "--check", str(patch), cwd=source)
            git("apply", str(patch), cwd=source)
        shutil.copytree(ROOT / "workspaces/arduino/adapter", source, dirs_exist_ok=True)
        shutil.copy2(
            ROOT / "workspaces/arduino/dependencies/frontend-package-lock.json",
            source / "frontend/package-lock.json",
        )
        shutil.copy2(
            ROOT / "workspaces/arduino/dependencies/backend-constraints.txt",
            source / "backend/constraints.txt",
        )
        shutil.copy2(ROOT / "Dockerfile", context / "Dockerfile")
        for name in ["scripts", "workspaces"]:
            shutil.copytree(ROOT / name, context / name)
        for name in ["grader", "course", "tests"]:
            if (ROOT / name).is_dir():
                shutil.copytree(ROOT / name, context / name)
            else:
                # The workspace's downloadable source excludes the grader,
                # course files and instructor fixtures, which only the grader
                # and test targets need.
                (context / name).mkdir()
        # Local offer of the adapter source, exact upstream source URL, and
        # build inputs. Questions and instructor answers are excluded.
        with tarfile.open(context / "pl-adapter-source.tar.gz", "w:gz") as tar:
            for name in [
                "workspaces",
                "Dockerfile",
                "scripts",
                "toolchain.lock.json",
                "LICENSE",
                "SOURCE.md",
            ]:
                tar.add(ROOT / name, arcname=name)
        (context / ".dockerignore").write_text(
            "**/node_modules\n**/.git\n**/__pycache__\nupstream/frontend/dist\n",
            encoding="utf-8",
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        # Stage on the destination filesystem so even a cross-device copy
        # failure cannot leave a partial build context at the requested path.
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}-", dir=output.parent
        ) as publish:
            staged = Path(publish) / "context"
            shutil.move(str(context), staged)
            staged.rename(output)
    print(f"Prepared {output}")
    print(f"Upstream: {lock['commit']}")
    print(f"Runtime: {lock['image']}")
    print(f"simavr: {lock['simavr_commit']}")


if __name__ == "__main__":
    main()
