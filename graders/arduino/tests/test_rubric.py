"""Gates, test items, partial credit and results, without the toolchain."""

from __future__ import annotations

import json
import tempfile
import types
from functools import cached_property
from pathlib import Path
from typing import Any

import pytest

import arduinograder as ag
from arduinograder import grading, rubric
from arduinograder.errors import INTERNAL_ERROR_MESSAGE
from arduinograder.grading import Grading
from arduinograder.pl import Submission
from arduinograder.sandbox import Budget, Sandbox
from arduinograder.toolchain import CompileError, Firmware

TRACE = ag.Trace.from_text(
    "P 0 13 I\nP 16000 13 L\nP 32000 13 H\nP 8000000 13 L\nT 32000000 reached"
)


def module_from(source: str, file: str | None = "/nowhere/tests/test.py") -> types.ModuleType:
    module = types.ModuleType("question_tests")
    module.__file__ = file
    exec(compile(source, "test.py", "exec"), module.__dict__)
    return module


class FakeGrading(Grading):
    """Grading with a canned trace instead of the toolchain."""

    def __init__(
        self,
        module: types.ModuleType,
        tmp_path: Path,
        source: str = "void loop() {}",
        params: dict[str, Any] | None = None,
    ) -> None:
        grade_dir = tmp_path / "grade"
        (grade_dir / "student").mkdir(parents=True, exist_ok=True)
        (grade_dir / "student/sketch.ino").write_text(source)
        if params is not None:
            (grade_dir / "data").mkdir(exist_ok=True)
            (grade_dir / "data/data.json").write_text(json.dumps({"params": params}))
        # prepare() refuses a used work directory, so each run gets a fresh one.
        work_dir = Path(tempfile.mkdtemp(prefix="work-", dir=tmp_path))
        super().__init__(module, Submission(grade_dir), Sandbox(work_dir), Budget(60))
        self.scenarios: list[ag.Scenario] = []

    @cached_property
    def firmware(self) -> Firmware:
        return Firmware(Path("/nowhere/sketch.elf"), "")

    def simulate(self, scenario: ag.Scenario) -> ag.Trace:
        self.scenarios.append(scenario)
        return TRACE


def test_items_are_collected_in_order_with_default_names() -> None:
    module = module_from(
        """
import arduinograder as ag

@ag.points(2)
def test_second_thing(trace): pass

@ag.gate
def no_foo(source): pass

@ag.name("Named")
@ag.description("About it")
@ag.points(1)
def test_first(trace): pass

def helper(): pass
"""
    )
    gates, items = rubric.collect(module)
    assert [gate.__name__ for gate in gates] == ["no_foo"]
    assert [(item.name, item.points, item.description) for item in items] == [
        ("Second thing", 2, ""),
        ("Named", 1, "About it"),
    ]


def test_each_item_runs_alone_and_scores_its_own_way(tmp_path: Path) -> None:
    module = module_from(
        """
import arduinograder as ag
scenario = ag.Scenario(duration_ms=2000)

@ag.points(1)
def test_assert(trace):
    assert trace.pin(13).at(3).is_high, "should be high"

@ag.points(1)
def test_assert_fails(trace):
    assert trace.pin(13).at(600).is_high, "LED off at 600 ms"

@ag.points(1)
def test_bare_assert_fails(trace):
    assert False

@ag.points(4)
def test_partial(trace, check):
    for ms, want in [(3, 1), (600, 0), (1200, 1), (1500, 0)]:
        check(trace.pin(13).level(ms) == want, f"at {ms} ms want {want}")
    return check.fraction

@ag.points(2)
def test_grader_bug(trace):
    trace.pin(13).at(99999)

@ag.points(2)
def test_bool(trace):
    return False

@ag.points(2)
def test_number(trace):
    return 0.25

@ag.points(1)
def test_stopped_simulation(simulate):
    crashed = ag.Trace.from_text("T 160000 crashed")
    crashed.pin(13).at(500)

@ag.points(1)
def test_nan(trace):
    return float("nan")

@ag.points(1)
def test_message_is_not_text(check):
    check(False, 42)
"""
    )
    grading = FakeGrading(module, tmp_path)
    results = grading.run().to_dict()
    assert results["gradable"] is True
    assert [(test["points"], test["message"]) for test in results["tests"]] == [
        (1.0, ""),
        (0.0, "LED off at 600 ms"),
        (0.0, "A check failed."),
        (3.0, "at 1200 ms want 1"),
        (0, rubric.GRADER_ERROR_MESSAGE),
        (0.0, ""),
        (0.5, ""),
        (0.0, "The program crashed at 10 ms, so the simulation stopped."),
        (0, rubric.GRADER_ERROR_MESSAGE),
        (0.0, "42"),
    ]
    assert results["score"] == pytest.approx(4.5 / 16)
    assert results["tests"][3]["max_points"] == 4
    json.dumps(results, allow_nan=False)


def test_fixtures_describe_the_submission(tmp_path: Path) -> None:
    module = module_from(
        """
import arduinograder as ag
from pathlib import Path

@ag.points(1)
def test_fixtures(source, sketch_name, params, data, tests_dir, submission, check):
    check(source == "void loop() { led(); }", "source")
    check(sketch_name == "sketch.ino", "sketch_name")
    check(params == {"pin": 13} and data == {"params": {"pin": 13}}, "params and data")
    check(tests_dir == Path("/nowhere/tests"), "tests_dir")
    check(submission.files == ["sketch.ino"] and submission.read("sketch.ino") == source, "files")
"""
    )
    results = FakeGrading(module, tmp_path, "void loop() { led(); }", params={"pin": 13}).run()
    assert results.score == 1.0, results.items[0].message


def test_gates_stop_grading_with_zero_points(tmp_path: Path) -> None:
    module = module_from(
        """
import arduinograder as ag
scenario = ag.Scenario(duration_ms=2000)
gates = [lambda source: "No foo allowed." if "foo" in source else None]

@ag.gate
def no_bar(source):
    if "bar" in source:
        raise ag.StopGrading("No bar allowed.")

@ag.gate
def led_on_at_600(source, trace):
    if "baz" in source:
        assert trace.pin(13).at(600).is_high, "LED off at 600 ms"

@ag.points(1)
def test_passes(trace):
    pass
"""
    )
    assert FakeGrading(module, tmp_path, "void loop() {}").run().score == 1.0
    for source, message in [
        ("void loop() { foo(); }", "No foo allowed."),
        ("void loop() { bar(); }", "No bar allowed."),
        ("void loop() { baz(); }", "LED off at 600 ms"),
    ]:
        stopped = FakeGrading(module, tmp_path, source).run()
        assert stopped.stopped and stopped.gradable and stopped.score == 0.0, source
        assert stopped.message == message and stopped.items == []


def test_stop_and_ungradable_from_tests_and_fixtures(tmp_path: Path) -> None:
    module = module_from(
        """
import arduinograder as ag
scenario = ag.Scenario(duration_ms=2000)

@ag.points(1)
def test_first(trace):
    pass

@ag.points(1)
def test_stops(trace):
    raise ag.StopGrading("Stopped by the test.")

@ag.points(1)
def test_never_runs(trace):
    pass
"""
    )
    results = FakeGrading(module, tmp_path).run()
    assert results.score == 0.0 and results.message == "Stopped by the test."
    assert [item.points for item in results.items] == [1]

    module = module_from(
        """
import arduinograder as ag

@ag.points(1)
def test_needs_sketch(source):
    pass
"""
    )
    grading = FakeGrading(module, tmp_path)
    (grading.submission.student_dir / "sketch.ino").unlink()
    results = grading.run()
    assert results.gradable is False and "No submission was found" in results.message


def test_trace_fixture_uses_module_or_item_scenario_once_each(tmp_path: Path) -> None:
    module = module_from(
        """
import arduinograder as ag
scenario = lambda: ag.Scenario(duration_ms=2000)
OWN = ag.Scenario(duration_ms=300).pulse(2, 1, at_ms=10, duration_ms=10)

@ag.points(1)
def test_a(trace): pass

@ag.points(1)
def test_b(trace): pass

@ag.with_scenario(OWN)
@ag.points(1)
def test_c(trace): pass

@ag.points(1)
def test_d(simulate):
    simulate(OWN)
"""
    )
    grading = FakeGrading(module, tmp_path)
    assert grading.run().score == 1.0
    assert [scenario.duration_ms for scenario in grading.scenarios] == [2000, 2000, 300, 300]


def test_mistakes_in_the_test_module_make_every_submission_ungradable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = [
        ("@ag.points(1)\ndef test_a(trace): pass\n", "needs scenario"),
        ("@ag.points(1)\ndef test_a(nonsense): pass\n", "no fixture named 'nonsense'"),
        (
            "@ag.gate\ndef gate(nonsense): pass\n@ag.points(1)\ndef test_a(source): pass\n",
            "no fixture named 'nonsense'",
        ),
        ("", "no tests worth points"),
        ("@ag.points(0)\ndef test_a(source): pass\n", "no tests worth points"),
    ]
    for source, cause in cases:
        results = FakeGrading(module_from("import arduinograder as ag\n" + source), tmp_path).run()
        assert not results.gradable and results.message == INTERNAL_ERROR_MESSAGE, source
        assert results.items == []
        assert cause in capsys.readouterr().err, source
    module = module_from(
        "import arduinograder as ag\n@ag.points(1)\ndef test_a(tests_dir): pass", None
    )
    results = FakeGrading(module, tmp_path).run()
    assert not results.gradable and "no tests_dir" in capsys.readouterr().err

    grade_dir = tmp_path / "grade"
    for budget in ("'45'", 0, -1, "1e999", True):
        module = module_from(
            f"import arduinograder as ag\nTIME_BUDGET_S = {budget}\n"
            "@ag.points(1)\ndef test_a(source): pass\n"
        )
        work_dir = Path(tempfile.mkdtemp(prefix="work-", dir=tmp_path))
        results = grading.grade(module, grade_dir=grade_dir, work_dir=work_dir)
        assert not results.gradable and results.message == INTERNAL_ERROR_MESSAGE, budget
        assert "TIME_BUDGET_S" in capsys.readouterr().err, budget


def test_full_marks_score_exactly_one_whatever_the_points(tmp_path: Path) -> None:
    module = module_from(
        "import arduinograder as ag\n"
        + "".join(
            f"@ag.points({points})\ndef test_{index}(source): pass\n"
            for index, points in enumerate([1 / 7] * 7 + [2 / 3, 10 / 3, 1 / 3, 0.1 * 3])
        )
    )
    results = FakeGrading(module, tmp_path).run()
    assert results.score == 1.0
    assert json.loads(json.dumps(results.to_dict()))["score"] == 1.0


def test_a_compile_error_stops_grading_before_any_test(tmp_path: Path) -> None:
    class Failing(FakeGrading):
        @cached_property
        def firmware(self) -> Firmware:
            raise CompileError("bad")

    module = module_from(
        """
import arduinograder as ag
scenario = ag.Scenario(duration_ms=2000)

@ag.points(1)
def test_source(source): pass

@ag.points(1)
def test_trace(trace): pass
"""
    )
    results = Failing(module, tmp_path).run()
    assert results.stopped and results.items == [] and "bad" in results.message
    source_only = module_from("import arduinograder as ag\n@ag.points(1)\ndef test_a(source): pass")
    assert Failing(source_only, tmp_path).run().score == 1.0
