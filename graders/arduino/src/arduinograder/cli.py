"""The ``arduinograder`` command: grade under PrairieLearn, or a sketch locally.

``python -m arduinograder`` and the ``arduinograder`` script both run
``main()``. Without arguments it grades PrairieLearn's ``/grade`` with
``/grade/tests/test.py``; with ``--sketch FILE`` it grades that file in a
temporary grading directory and prints the results.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from .grading import WORK_DIR, grade
from .pl import GRADE_DIR
from .rubric import collect


def _test_module(
    tests: str | None, module: ModuleType | None, grade_dir: Path
) -> ModuleType | str | None:
    """Return the test module to grade with, or ``None`` if there is none.

    In order: the file named on the command line, the module the caller
    gave, the running script when it defines tests (a test file ending in
    ``main()``), and ``tests/test.py`` under the grading directory, which
    is PrairieLearn's layout and the image's default.
    """
    if tests:
        return tests
    if module is not None:
        return module
    running = sys.modules.get("__main__")
    if running is not None and any(collect(running)):
        return running
    default = grade_dir / "tests/test.py"
    return str(default) if default.is_file() else None


def main(argv: Sequence[str] | None = None, module: ModuleType | None = None) -> int:
    """Grade as PrairieLearn's entry point, or a sketch locally with ``--sketch``.

    Without a ``tests`` argument, grades with ``module``, with the running
    ``__main__`` module when it is a test file ending in ``ag.main()``, or
    else with ``tests/test.py`` under the grading directory.

    Args:
        argv: Command-line arguments; by default ``sys.argv[1:]``.
        module: The test module to use when none is named on the command line.

    Returns:
        The exit status, always 0: results go to ``results.json`` or stdout.
    """
    parser = argparse.ArgumentParser(
        prog="arduinograder", description="Grade an Arduino sketch with a question's tests."
    )
    parser.add_argument(
        "tests",
        nargs="?",
        help="the question's tests/test.py; by default tests/test.py in the grading directory",
    )
    parser.add_argument(
        "--grade-dir", type=Path, default=GRADE_DIR, help="PrairieLearn's grading directory"
    )
    parser.add_argument(
        "--work-dir", type=Path, default=WORK_DIR, help="where to compile and simulate"
    )
    parser.add_argument(
        "--sketch",
        type=Path,
        help="grade this sketch instead of a submission and print the results",
    )
    parser.add_argument("--name", default="sketch.ino", help="submitted file name for --sketch")
    parser.add_argument("--params", default="{}", help="JSON params for --sketch")
    args = parser.parse_args(argv)
    target = _test_module(args.tests, module, args.grade_dir)
    if target is None:
        parser.error(
            f"give the question's tests/test.py: there is no {args.grade_dir}/tests/test.py"
        )
    if args.sketch is None:
        grade(target, grade_dir=args.grade_dir, work_dir=args.work_dir)
        return 0
    with tempfile.TemporaryDirectory() as temporary:
        grade_dir = Path(temporary) / "grade"
        (grade_dir / "student").mkdir(parents=True)
        shutil.copyfile(args.sketch, grade_dir / "student" / args.name)
        (grade_dir / "data").mkdir()
        (grade_dir / "data/data.json").write_text(
            json.dumps({"params": json.loads(args.params)}), encoding="utf-8"
        )
        results = grade(target, grade_dir=grade_dir, work_dir=args.work_dir)
    print(json.dumps(results.to_dict(), indent=2))
    return 0
