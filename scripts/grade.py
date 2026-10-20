#!/usr/bin/env python3
"""Grade sketches with a question's tests/test.py, laid out as PrairieLearn does.

With no sketches, grade every case in QUESTION/grader-cases and compare the
scores with grader-cases/expected.json ({"case.ino": score, ...}; null means
the submission must be ungradable). Runs the grader image under the
production grader limits: no network, 0.9 CPU and 2 GiB of memory.
"""

import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


def grade(question, image, sketch, name):
    options = json.loads((question / "info.json").read_text())["externalGradingOptions"]
    entrypoint = options.get("entrypoint", "python3 /grade/tests/test.py")
    if isinstance(entrypoint, str):
        entrypoint = shlex.split(entrypoint)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        files = root / "grade"
        shutil.copytree(question / "tests", files / "tests")
        (files / "student").mkdir()
        shutil.copyfile(sketch, files / "student" / name)
        (files / "data").mkdir()
        (files / "data/data.json").write_text(json.dumps({"params": {}}))
        # Copy files in and out, as PrairieLearn does, rather than bind-mounting
        # a directory that the root-run grader would chmod.
        container = docker(
            "create", "--network", "none", "--cpus", "0.9", "--memory", "2g",
            "--entrypoint", entrypoint[0], image, *entrypoint[1:],
            capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip
        try:
            docker("cp", f"{files}/.", f"{container}:/grade", capture_output=True)
            try:
                started = docker(
                    "start", "--attach", container, capture_output=True, text=True,
                    timeout=options.get("timeout", 30),
                )  # fmt: skip
                log = started.stdout + started.stderr
            except subprocess.TimeoutExpired:
                return None, "Grading timed out."
            results = root / "results.json"
            copied = subprocess.run(
                [
                    "docker",
                    "cp",
                    f"{container}:/grade/results/results.json",
                    str(results),
                ],
                capture_output=True,
            )
            if copied.returncode:
                return None, f"No results.json was written.\n{log}"
            return json.loads(results.read_text()), log
        finally:
            subprocess.run(["docker", "rm", "--force", container], capture_output=True)


def describe(results):
    if results is None:
        return "no result"
    if not results["gradable"]:
        return "ungradable"
    return f"score {results['score']:.3f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", type=Path, help="question directory")
    parser.add_argument("sketches", type=Path, nargs="*", help="sketches to grade")
    parser.add_argument("--image", help="grader image (default: from info.json)")
    parser.add_argument("--name", default="sketch.ino", help="submitted file name")
    parser.add_argument("--verbose", action="store_true", help="print full results")
    args = parser.parse_args()
    question = args.question.resolve()
    image = (
        args.image
        or json.loads((question / "info.json").read_text())["externalGradingOptions"][
            "image"
        ]
    )

    if args.sketches:
        for sketch in args.sketches:
            results, log = grade(question, image, sketch, args.name)
            print(f"{sketch}: {describe(results)}")
            if args.verbose or results is None:
                print(json.dumps(results, indent=2) if results else log)
        return 0

    expected = json.loads((question / "grader-cases/expected.json").read_text())
    failures = 0
    for case, score in expected.items():
        results, log = grade(
            question, image, question / "grader-cases" / case, args.name
        )
        if score is None:
            passed = results is not None and results["gradable"] is False
        else:
            passed = (
                results is not None
                and results["gradable"]
                and abs(results["score"] - score) < 1e-9
            )
        failures += not passed
        wanted = "ungradable" if score is None else f"score {score:.3f}"
        print(
            f"{'ok  ' if passed else 'FAIL'} {case}: {describe(results)} (expected {wanted})"
        )
        if not passed or args.verbose:
            print(json.dumps(results, indent=2) if results else log)
    print(
        f"{question.name}: {len(expected) - failures}/{len(expected)} cases as expected"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
