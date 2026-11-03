"""PrairieLearn's layout, results.json, hiding /grade, and the command line."""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from arduinograder import cli, grading, pl, rubric
from arduinograder.errors import INTERNAL_ERROR_MESSAGE
from arduinograder.pl import Results
from arduinograder.rubric import ItemResult


def module_from(source: str) -> types.ModuleType:
    module = types.ModuleType("question_tests")
    module.__file__ = "/nowhere/tests/test.py"
    exec(compile(source, "test.py", "exec"), module.__dict__)
    return module


def test_results_json_shape(tmp_path: Path) -> None:
    results = Results()
    results.add(rubric.ItemResult("One", 1, 2, "d", "m"))
    results.add_message("first")
    results.add_message("second")
    results.write(tmp_path)
    written = json.loads((tmp_path / "results/results.json").read_text())
    assert written == {
        "gradable": True,
        "score": 0.5,
        "message": "first\n\nsecond",
        "tests": [
            {"name": "One", "description": "d", "points": 1, "max_points": 2, "message": "m"}
        ],
    }
    assert Results().score == 0.0


def test_grading_the_pl_directory_needs_the_sandbox_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    grade_dir = tmp_path / "grade"
    (grade_dir / "student").mkdir(parents=True)
    (grade_dir / "student/sketch.ino").write_text("void loop() {}")
    monkeypatch.setattr(grading, "GRADE_DIR", grade_dir)
    monkeypatch.setattr("arduinograder.sandbox.os.geteuid", lambda: 1000)
    module = module_from("import arduinograder as ag\n@ag.points(1)\ndef test_a(source): pass\n")
    results = grading.grade(module, grade_dir=grade_dir, work_dir=tmp_path / "work")
    assert not results.gradable and results.message == INTERNAL_ERROR_MESSAGE
    assert "sandbox user" in capsys.readouterr().err
    assert json.loads((grade_dir / "results/results.json").read_text())["gradable"] is False


def test_protect_hides_the_grading_files_but_not_the_directory_or_results(tmp_path: Path) -> None:
    grade_dir = tmp_path / "grade"
    for name in ("tests", "student", "results"):
        (grade_dir / name).mkdir(parents=True)
        (grade_dir / name / "file").write_text("x")
    before = {path: path.stat().st_mode for path in [grade_dir, *grade_dir.rglob("*")]}
    pl.protect(grade_dir)
    for path in (grade_dir / "tests", grade_dir / "tests/file", grade_dir / "student/file"):
        assert path.stat().st_mode & 0o077 == 0
    for path in (grade_dir, grade_dir / "results", grade_dir / "results/file"):
        assert path.stat().st_mode == before[path]


def test_main_defaults_to_the_tests_under_the_grading_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    grade_dir = tmp_path / "grade"
    (grade_dir / "tests").mkdir(parents=True)
    (grade_dir / "tests/test.py").write_text(
        "import arduinograder as ag\n@ag.points(1)\ndef test_a(source): assert 'loop' in source\n"
    )
    sketch = tmp_path / "attempt.ino"
    sketch.write_text("void loop() {}")
    work = ["--work-dir", str(tmp_path / "work")]
    assert cli.main(["--grade-dir", str(grade_dir), *work, "--sketch", str(sketch)]) == 0
    assert json.loads(capsys.readouterr().out)["score"] == 1.0
    with pytest.raises(SystemExit):
        cli.main(["--grade-dir", str(tmp_path / "elsewhere"), *work, "--sketch", str(sketch)])


def test_results_with_nan_are_written_as_ungradable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results = Results()
    results.add(ItemResult("Nan", float("nan"), 1))
    results.write(tmp_path)
    written = json.loads((tmp_path / "results/results.json").read_text())
    assert written["gradable"] is False and written["message"] == INTERNAL_ERROR_MESSAGE
    assert "ValueError" in capsys.readouterr().err


def test_an_unguarded_main_in_the_test_file_grades_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    grade_dir = tmp_path / "grade"
    (grade_dir / "tests").mkdir(parents=True)
    (grade_dir / "tests/test.py").write_text(
        "import arduinograder as ag\n@ag.points(1)\ndef test_a(source): assert 'loop' in source\n"
        "ag.main()\n"
    )
    sketch = tmp_path / "attempt.ino"
    sketch.write_text("void loop() {}")
    work = ["--work-dir", str(tmp_path / "work")]
    assert cli.main(["--grade-dir", str(grade_dir), *work, "--sketch", str(sketch)]) == 0
    assert json.loads(capsys.readouterr().out)["score"] == 1.0


def test_loading_a_test_module_works_like_running_it(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "helpers.py").write_text("PIN = 13\n")
    (tests / "test.py").write_text(
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n"
        "import arduinograder as ag\n"
        "from helpers import PIN\n"
        "@dataclass\n"
        "class Pins:\n"
        "    led: int = PIN\n"
        "@ag.points(1)\n"
        "def test_led(source): assert Pins().led == 13\n"
    )
    module = grading.load_module(tests / "test.py")
    assert [item.name for item in rubric.collect(module)[1]] == ["Led"]
