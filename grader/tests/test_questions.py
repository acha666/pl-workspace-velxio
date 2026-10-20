"""Course questions score their grader cases as recorded in expected.json."""

import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil

import pytest

COURSE = Path(os.environ.get("COURSE_DIR", "/opt/course"))
CASES = sorted(
    (question, case, score)
    for expected in COURSE.glob("questions/**/grader-cases/expected.json")
    for question in [expected.parent.parent]
    for case, score in json.loads(expected.read_text()).items()
)
_runs = itertools.count()


def grade(tmp_path, question, sketch, name="sketch.ino", data='{"params": {}}'):
    """Run a question's tests/test.py on one sketch, as PrairieLearn lays it out."""
    grade_dir = tmp_path / "grade"
    shutil.copytree(question / "tests", grade_dir / "tests")
    (grade_dir / "student").mkdir()
    (grade_dir / "student" / name).write_text(sketch)
    (grade_dir / "data").mkdir()
    (grade_dir / "data/data.json").write_text(data)
    spec = importlib.util.spec_from_file_location(
        "question_test", grade_dir / "tests/test.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    work_dir = Path(f"/tmp/arduinograder-question-{next(_runs)}")
    module.QuestionGrader(grade_dir=grade_dir, work_dir=work_dir).start()
    return json.loads((grade_dir / "results/results.json").read_text())


def test_course_questions_have_grader_cases():
    assert CASES, f"No grader cases found under {COURSE}"


@pytest.mark.parametrize(
    "question,case,score", CASES, ids=[f"{q.name}/{c}" for q, c, _ in CASES]
)
def test_grader_case(tmp_path, question, case, score):
    results = grade(tmp_path, question, (question / "grader-cases" / case).read_text())
    if score is None:
        assert results["gradable"] is False
    else:
        assert results["gradable"] is True, results["message"]
        assert results["score"] == pytest.approx(score), results


def test_sketch_cannot_read_grading_files(tmp_path):
    question = COURSE / "questions/arduino/blinkWithoutDelay"
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
    assert not (grade_dir / "tests").stat().st_mode & 0o077


def test_compile_errors_name_the_submitted_file(tmp_path):
    question = COURSE / "questions/arduino/blinkWithoutDelay"
    results = grade(
        tmp_path, question, "void setup() {}\nvoid loop() { oops }\n", "lab.ino"
    )
    assert results["score"] == 0
    assert "lab.ino:2:" in results["message"]
    for noise in ["/tmp/", "\x1b", "Used platform", "/opt/arduino"]:
        assert noise not in results["message"]


def test_grader_failures_still_write_ungradable_results(tmp_path):
    question = COURSE / "questions/arduino/blinkWithoutDelay"
    reference = (question / "grader-cases/reference.ino").read_text()
    results = grade(tmp_path, question, reference, data="not json")
    assert results["gradable"] is False
    assert "grader failed unexpectedly" in results["message"]


def test_missing_sketch_is_not_counted(tmp_path):
    question = COURSE / "questions/arduino/blinkWithoutDelay"
    results = grade(tmp_path, question, "", "notes.txt")
    assert results["gradable"] is False
    assert "No submission was found" in results["message"]
