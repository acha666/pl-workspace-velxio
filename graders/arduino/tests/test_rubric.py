"""Gates, test items, partial credit and results, without the toolchain."""

from __future__ import annotations

import json
import types
from functools import cached_property
from pathlib import Path

import pytest

import arduinograder as ag
from arduinograder import rubric
from arduinograder.errors import INTERNAL_ERROR_MESSAGE
from arduinograder.grading import Grading
from arduinograder.pl import Submission
from arduinograder.sandbox import Budget, Sandbox
from arduinograder.toolchain import Firmware

TRACE = ag.Trace.from_text(
    "P 0 13 I\nP 16000 13 L\nP 32000 13 H\nP 8000000 13 L\nT 32000000 reached"
)


def module_from(source: str) -> types.ModuleType:
    module = types.ModuleType("question_tests")
    module.__file__ = "/nowhere/tests/test.py"
    exec(compile(source, "test.py", "exec"), module.__dict__)
    return module


class FakeGrading(Grading):
    """Grading with a canned trace instead of the toolchain."""

    def __init__(self, module: types.ModuleType, tmp_path: Path, source: str = "void loop() {}"):
        grade_dir = tmp_path / "grade"
        (grade_dir / "student").mkdir(parents=True, exist_ok=True)
        (grade_dir / "student/sketch.ino").write_text(source)
        super().__init__(module, Submission(grade_dir), Sandbox(tmp_path / "work"), Budget(60))
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
    ]
    assert results["score"] == pytest.approx(4.5 / 14)
    assert results["tests"][3]["max_points"] == 4
    json.dumps(results)


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

@ag.points(1)
def test_passes(trace):
    pass
"""
    )
    assert FakeGrading(module, tmp_path, "void loop() {}").run().score == 1.0
    stopped = FakeGrading(module, tmp_path, "void loop() { foo(); }").run()
    assert stopped.score == 0.0 and stopped.gradable and stopped.message == "No foo allowed."
    assert stopped.items == []
    stopped = FakeGrading(module, tmp_path, "void loop() { bar(); }").run()
    assert stopped.score == 0.0 and stopped.message == "No bar allowed."


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
    for source in [
        "import arduinograder as ag\n@ag.points(1)\ndef test_a(trace): pass\n",
        "import arduinograder as ag\n@ag.points(1)\ndef test_a(nonsense): pass\n",
        "import arduinograder as ag\n@ag.gate\ndef gate(nonsense): pass\n",
    ]:
        results = FakeGrading(module_from(source), tmp_path).run()
        assert not results.gradable and results.message == INTERNAL_ERROR_MESSAGE, source
        assert results.items == []
        assert "ConfigurationError" in capsys.readouterr().err


def test_a_time_budget_that_is_not_a_positive_number_is_a_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from arduinograder import grading

    grade_dir = tmp_path / "grade"
    (grade_dir / "student").mkdir(parents=True)
    (grade_dir / "student/sketch.ino").write_text("void loop() {}")
    for budget in ("45", 0, -1, float("inf"), True):
        module = module_from("import arduinograder as ag\n@ag.points(1)\ndef test_a(source): pass")
        vars(module)["TIME_BUDGET_S"] = budget
        results = grading.grade(module, grade_dir=grade_dir, work_dir=tmp_path / "work")
        assert not results.gradable, budget
        assert "TIME_BUDGET_S" in capsys.readouterr().err


def test_a_module_without_tests_worth_points_is_a_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for source in [
        "import arduinograder as ag\n",
        "import arduinograder as ag\n@ag.points(0)\ndef test_a(source): pass\n",
    ]:
        results = FakeGrading(module_from(source), tmp_path).run()
        assert not results.gradable and results.message == INTERNAL_ERROR_MESSAGE
        assert "no tests worth points" in capsys.readouterr().err
