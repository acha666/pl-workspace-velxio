"""PrairieLearn's layout, results.json, hiding /grade, and the command line."""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from arduinograder import cli, grading, pl, rubric
from arduinograder.errors import INTERNAL_ERROR_MESSAGE, Ungradable
from arduinograder.pl import Results, Submission
from arduinograder.rubric import ItemResult


def module_from(source: str) -> types.ModuleType:
    module = types.ModuleType("question_tests")
    module.__file__ = "/nowhere/tests/test.py"
    exec(compile(source, "test.py", "exec"), module.__dict__)
    return module


def test_results_json_shape_and_size_limits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results = Results()
    results.add(ItemResult("One", 1, 2, "d", "m"))
    results.add(ItemResult("Long", 0, 1, message="x" * 20_000))
    results.add_message("first")
    results.add_message("y" * 20_000)
    results.write(tmp_path)
    written = json.loads((tmp_path / "results/results.json").read_text())
    assert written["gradable"] is True and written["score"] == 1 / 3
    assert written["tests"][0] == {
        "name": "One",
        "description": "d",
        "points": 1,
        "max_points": 2,
        "message": "m",
    }
    long = written["tests"][1]["message"]
    assert long.startswith("x" * pl.MAX_MESSAGE_CHARS) and long.endswith("[message truncated]")
    assert len(long) < pl.MAX_MESSAGE_CHARS + 100
    assert written["message"].startswith("first\n\nyyy")
    assert written["message"].endswith("[message truncated]")
    assert Results().to_dict() == {"gradable": True, "score": 0.0, "message": "", "tests": []}

    stopped = Results()
    stopped.add(ItemResult("One", 1, 1))
    stopped.stopped = True
    assert stopped.score == 0.0

    nan = Results()
    nan.add(ItemResult("Nan", float("nan"), 1))
    nan.write(tmp_path)
    written = json.loads((tmp_path / "results/results.json").read_text())
    assert written["gradable"] is False and written["message"] == INTERNAL_ERROR_MESSAGE
    assert "ValueError" in capsys.readouterr().err


def test_the_sketch_to_grade_is_found_or_named(tmp_path: Path) -> None:
    student = tmp_path / "student"
    student.mkdir()
    (student / "notes.txt").write_text("")
    with pytest.raises(Ungradable, match="Submit an Arduino sketch"):
        Submission(tmp_path).sketch_path  # noqa: B018
    (student / "a.ino").write_text("// a")
    assert Submission(tmp_path).sketch_name == "a.ino" and Submission(tmp_path).source == "// a"
    (student / "b.ino").write_text("// b")
    with pytest.raises(Ungradable, match=r"Several sketches were submitted \(a.ino, b.ino\)"):
        Submission(tmp_path).sketch_path  # noqa: B018
    assert Submission(tmp_path, sketch_file="b.ino").source == "// b"
    with pytest.raises(Ungradable, match=r"Submit lab\.ino"):
        Submission(tmp_path, sketch_file="lab.ino").sketch_path  # noqa: B018
    (student / "sketch.ino").write_text("// sketch")
    submission = Submission(tmp_path)
    assert submission.source == "// sketch"
    assert submission.files == ["a.ino", "b.ino", "notes.txt", "sketch.ino"]
    (student / "sketch.ino").unlink()
    (tmp_path / "secret").write_text("// secret")
    (student / "sketch.ino").symlink_to(tmp_path / "secret")
    with pytest.raises(Ungradable, match="No submission"):
        Submission(tmp_path).sketch_path  # noqa: B018
    assert Submission(tmp_path / "nowhere").files == []


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


def test_the_command_line_grades_a_sketch_with_the_question_tests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    grade_dir = tmp_path / "grade"
    (grade_dir / "tests").mkdir(parents=True)
    # Without the __main__ guard, ag.main() runs while the module is imported
    # to grade, and must not grade again from there.
    (grade_dir / "tests/test.py").write_text(
        "import arduinograder as ag\n"
        "@ag.points(1)\n"
        "def test_a(source, sketch_name, params):\n"
        "    assert 'loop' in source and sketch_name == 'lab.ino' and params == {'n': 3}\n"
        "ag.main()\n"
    )
    sketch = tmp_path / "attempt.ino"
    sketch.write_text("void loop() {}")
    args = ["--grade-dir", str(grade_dir), "--work-dir", str(tmp_path / "work")]
    assert (
        cli.main([*args, "--sketch", str(sketch), "--name", "lab.ino", "--params", '{"n": 3}']) == 0
    )
    printed = json.loads(capsys.readouterr().out)
    assert printed["score"] == 1.0, printed
    with pytest.raises(SystemExit):
        cli.main(["--grade-dir", str(tmp_path / "elsewhere"), "--sketch", str(sketch)])


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
    (tests / "notes.txt").write_text("not a module")
    with pytest.raises(ImportError):
        grading.load_module(tests / "notes.txt")
