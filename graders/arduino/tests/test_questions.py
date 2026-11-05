"""Course question tests score sketches in cases/ as recorded in expected.json.

cases/<path under questions/>/ holds temporary regression sketches for the
bundled templates. They test the grader and are not part of a question.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from arduinograder import grading
from conftest import COURSE

pytestmark = pytest.mark.usefixtures("requires_toolchain")

CASE_DIR = Path(__file__).parent / "cases"
# The autograded template that the grader behaviour tests submit to.
EXAMPLE = "arduino/blinkWithoutDelay"
CASES: list[tuple[Path, Path, float | None]] = sorted(
    (COURSE / "questions" / cases.relative_to(CASE_DIR), cases / case, score)
    for expected in CASE_DIR.glob("**/expected.json")
    for cases in [expected.parent]
    for case, score in json.loads(expected.read_text()).items()
)
_runs = itertools.count()


def grade(
    tmp_path: Path,
    question: Path,
    sketch: str,
    name: str = "sketch.ino",
    data: str = '{"params": {}}',
) -> dict[str, Any]:
    """Run a question's tests/test.py on one sketch, as PrairieLearn lays it out."""
    grade_dir = tmp_path / "grade"
    shutil.copytree(question / "tests", grade_dir / "tests")
    (grade_dir / "student").mkdir()
    (grade_dir / "student" / name).write_text(sketch)
    (grade_dir / "data").mkdir()
    (grade_dir / "data/data.json").write_text(data)
    work_dir = Path(f"/tmp/arduinograder-question-{next(_runs)}")
    grading.grade(grade_dir / "tests/test.py", grade_dir=grade_dir, work_dir=work_dir)
    results: dict[str, Any] = json.loads((grade_dir / "results/results.json").read_text())
    return results


def test_grader_cases_list_their_sketches_for_existing_questions() -> None:
    assert CASES, f"No grader cases found under {CASE_DIR}"
    for expected in CASE_DIR.glob("**/expected.json"):
        cases = expected.parent
        assert sorted(json.loads(expected.read_text())) == sorted(
            path.name for path in cases.glob("*.ino")
        )
        question = COURSE / "questions" / cases.relative_to(CASE_DIR)
        assert (question / "tests/test.py").is_file(), question


@pytest.mark.parametrize(
    "question,case,score", CASES, ids=[f"{q.name}/{c.name}" for q, c, _ in CASES]
)
def test_grader_case(tmp_path: Path, question: Path, case: Path, score: float | None) -> None:
    results = grade(tmp_path, question, case.read_text())
    if score is None:
        assert results["gradable"] is False
    else:
        assert results["gradable"] is True, results["message"]
        assert results["score"] == pytest.approx(score), results


def test_feedback_tells_the_student_what_happened(tmp_path: Path) -> None:
    question = COURSE / "questions" / EXAMPLE
    wrong = (CASE_DIR / EXAMPLE / "wrong-period.ino").read_text()
    results = grade(tmp_path, question, wrong)
    output, blink = results["tests"]
    assert output["points"] == 1 and output["message"] == ""
    assert blink["points"] == 0 and "At 750 ms the LED should be off." in blink["message"]
    assert re.search(r"It switched at: 100\d ms, 200\d ms\.", blink["message"])
    delayed = (CASE_DIR / EXAMPLE / "uses-delay.ino").read_text()
    results = grade(tmp_path / "delayed", question, delayed)
    assert results["score"] == 0 and "calls delay()" in results["message"]
    assert results["tests"] == []


def test_sketch_cannot_read_grading_files(tmp_path: Path) -> None:
    question = COURSE / "questions" / EXAMPLE
    secret = "SECRET-EXPECTED-OUTPUT"
    sketch = (
        '#include "/grade/tests/secret.h"\n'
        '#include "/grade/data/data.json"\n'
        "void setup() {}\nvoid loop() {}\n"
    )
    grade_dir = tmp_path / "grade"
    tests = tmp_path / "question/tests"
    shutil.copytree(question / "tests", tests)
    (tests / "secret.h").write_text(f'const char *s = "{secret}";\n#error {secret}\n')
    results = grade(tmp_path, tests.parent, sketch)
    assert results["gradable"] is True and results["score"] == 0
    assert "did not compile" in results["message"]
    assert secret not in json.dumps(results)
    if os.geteuid() == 0:
        assert not (grade_dir / "tests").stat().st_mode & 0o077


def test_compile_errors_name_the_submitted_file(tmp_path: Path) -> None:
    question = COURSE / "questions" / EXAMPLE
    results = grade(tmp_path, question, "void setup() {}\nvoid loop() { oops }\n", "lab.ino")
    assert results["score"] == 0
    assert "lab.ino:2:" in results["message"]
    for noise in ["/tmp/", "\x1b", "Used platform", "/opt/arduino"]:
        assert noise not in results["message"]


def test_grader_failures_still_write_ungradable_results(tmp_path: Path) -> None:
    question = COURSE / "questions" / EXAMPLE
    reference = (CASE_DIR / EXAMPLE / "reference.ino").read_text()
    results = grade(tmp_path, question, reference, data="not json")
    assert results["gradable"] is False
    assert "grader failed unexpectedly" in results["message"]
    broken = tmp_path / "broken/tests"
    broken.mkdir(parents=True)
    (broken / "test.py").write_text("this is not python\n")
    results = grade(tmp_path / "b", broken.parent, reference)
    assert results["gradable"] is False


def test_missing_sketch_is_not_counted(tmp_path: Path) -> None:
    question = COURSE / "questions" / EXAMPLE
    results = grade(tmp_path, question, "", "notes.txt")
    assert results["gradable"] is False
    assert "No submission was found" in results["message"]


def test_command_line_grades_a_sketch_locally() -> None:
    tests = COURSE / "questions" / EXAMPLE / "tests/test.py"
    reference = CASE_DIR / EXAMPLE / "reference.ino"
    wrong = CASE_DIR / EXAMPLE / "wrong-period.ino"
    scores = []
    for command in [
        [sys.executable, "-m", "arduinograder", str(tests), "--sketch", str(reference)],
        [sys.executable, str(tests), "--sketch", str(wrong), "--name", "lab.ino"],
    ]:
        # Each run needs an unused work directory; the default would be reused.
        work = ["--work-dir", f"/tmp/arduinograder-cli-{next(_runs)}"]
        completed = subprocess.run([*command, *work], capture_output=True, text=True, check=True)
        results = json.loads(completed.stdout)
        assert results["gradable"] is True, completed.stderr
        scores.append(results["score"])
    assert scores == [1.0, 0.25]
