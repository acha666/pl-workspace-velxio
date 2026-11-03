"""Grading one submission with a test module: the fixtures, and the run.

A test or gate names the fixtures it needs as parameters. ``Grading``
supplies them, compiling the sketch once and simulating each distinct
scenario once, and runs the module's gates and then its tests. ``grade()``
does that for the submission PrairieLearn lays out and writes the results.
"""

from __future__ import annotations

import importlib.util
import os
import traceback
from functools import cached_property
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from .errors import INTERNAL_ERROR_MESSAGE, StopGrading, Ungradable
from .pl import GRADE_DIR, Results, Submission, protect
from .rubric import Item, collect, run_gate, run_item
from .sandbox import SANDBOX_USER, Budget, Sandbox
from .sim import Scenario, ScenarioKey, Session, Simulator, Trace
from .toolchain import Compiler, Firmware

WORK_DIR: Final = Path("/tmp/arduinograder")
"""Where sketches are compiled and simulated, unless ``grade()`` is told otherwise."""
DEFAULT_TIME_BUDGET_S: Final = 45
"""The wall-clock budget for compiling and simulating, unless the module sets ``TIME_BUDGET_S``."""

FIXTURE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "submission",
        "source",
        "sketch_name",
        "params",
        "data",
        "tests_dir",
        "compiler",
        "firmware",
        "simulator",
        "simulate",
        "session",
    }
)
"""The fixtures that are attributes of ``Grading``; ``trace`` and ``check`` are made per test."""


class Grading:
    """One run of a test module's gates and tests on one submission.

    Every fixture in ``FIXTURE_NAMES`` is an attribute of the same name,
    created on first use and kept for the rest of the run, so the sketch is
    compiled at most once. ``resolve()`` looks fixtures up by name for
    ``rubric.run_gate()`` and ``rubric.run_item()``, adding ``trace``, which
    depends on the test's scenario.

    Attributes:
        module: The question's test module.
        submission: What is being graded.
        sandbox: Where tools run.
        budget: The wall-clock budget for compiling and simulating.
        results: Filled in by ``run()``.
    """

    def __init__(
        self, module: ModuleType, submission: Submission, sandbox: Sandbox, budget: Budget
    ) -> None:
        """Prepare to grade; nothing runs until ``run()``."""
        self.module = module
        self.submission = submission
        self.sandbox = sandbox
        self.budget = budget
        self.results = Results()
        self._traces: dict[ScenarioKey, Trace] = {}

    # -- Fixtures ---------------------------------------------------------------

    @property
    def source(self) -> str:
        """The submitted sketch's text."""
        return self.submission.source

    @property
    def sketch_name(self) -> str:
        """The submitted sketch's file name."""
        return self.submission.sketch_name

    @property
    def params(self) -> dict[str, Any]:
        """The question's params from PrairieLearn's ``data.json``."""
        return self.submission.params

    @property
    def data(self) -> dict[str, Any]:
        """PrairieLearn's ``data.json``, or an empty dict without one."""
        return self.submission.data

    @property
    def tests_dir(self) -> Path:
        """The directory of the test module, for reference files kept next to it.

        Raises:
            LookupError: If the module was not loaded from a file.
        """
        if not self.module.__file__:
            raise LookupError("The test module has no file, so there is no tests_dir.")
        return Path(self.module.__file__).parent

    @cached_property
    def compiler(self) -> Compiler:
        """The compiler, bound to the sandbox and the budget."""
        return Compiler(self.sandbox, self.budget)

    @cached_property
    def simulator(self) -> Simulator:
        """The simulator, bound to the sandbox and the budget."""
        return Simulator(self.sandbox, self.budget)

    @cached_property
    def firmware(self) -> Firmware:
        """The compiled sketch; a compile error stops grading with score 0."""
        return self.compiler.compile(self.submission.source, name=self.submission.sketch_name)

    def simulate(self, scenario: Scenario) -> Trace:
        """Run the compiled sketch through a scenario; each distinct scenario runs once."""
        key = scenario.key
        if key not in self._traces:
            self._traces[key] = self.simulator.run(self.firmware, scenario)
        return self._traces[key]

    def session(self, *, max_pin_changes: int = 200_000, max_serial_bytes: int = 65_536) -> Session:
        """Start the compiled sketch from reset in a session."""
        return self.simulator.session(
            self.firmware, max_pin_changes=max_pin_changes, max_serial_bytes=max_serial_bytes
        )

    def resolve(self, name: str, item: Item | None = None, /) -> object:
        """Return the fixture a test or gate named as a parameter.

        Args:
            name: The parameter name.
            item: The test being run, whose own scenario ``trace`` uses; ``None``
                for a gate.

        Raises:
            LookupError: If there is no such fixture.
        """
        if name == "trace":
            return self.simulate(self._scenario_for(item))
        if name not in FIXTURE_NAMES:
            raise LookupError(f"There is no fixture named {name!r}.")
        return getattr(self, name)

    def _scenario_for(self, item: Item | None) -> Scenario:
        """Return the test's own scenario, else the module's ``scenario``, calling it if needed."""
        scenario: object = getattr(self.module, "scenario", None)
        if item is not None and item.scenario is not None:
            scenario = item.scenario
        if callable(scenario) and not isinstance(scenario, Scenario):
            scenario = scenario()
        if not isinstance(scenario, Scenario):
            raise LookupError(
                "The trace fixture needs scenario = Scenario(...) in the test module "
                "or @with_scenario(...) on the test."
            )
        return scenario

    # -- Running ----------------------------------------------------------------

    def run(self) -> Results:
        """Run the gates, then every test, and return the results.

        A ``StopGrading`` zeroes the score with its message; an ``Ungradable``
        or an unexpected error outside a test marks the submission ungradable.
        """
        gates, items = collect(self.module)
        try:
            self.sandbox.prepare()
            for func in gates:
                run_gate(func, self.resolve)
            for item in items:
                self.results.add(run_item(item, self.resolve))
        except StopGrading as stop:
            self.results.stopped = True
            self.results.add_message(str(stop))
        except Ungradable as error:
            self.results.gradable = False
            self.results.add_message(str(error))
        except Exception:
            traceback.print_exc()
            self.results.gradable = False
            self.results.add_message(INTERNAL_ERROR_MESSAGE)
        return self.results


def load_module(path: str | os.PathLike[str]) -> ModuleType:
    """Import a test module from its file path.

    Raises:
        ImportError: If the file cannot be loaded as a module.
    """
    path = Path(path)
    spec = importlib.util.spec_from_file_location("question_tests", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load the test module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def grade(
    module: ModuleType | str | os.PathLike[str],
    *,
    grade_dir: str | os.PathLike[str] = GRADE_DIR,
    work_dir: str | os.PathLike[str] = WORK_DIR,
    sandbox: Sandbox | None = None,
) -> Results:
    """Grade the submission under ``grade_dir`` with a test module.

    The module may set ``TIME_BUDGET_S`` (default 45) and ``SKETCH_FILE``
    (default: ``sketch.ino``, else the only ``.ino`` submitted). Whatever
    happens, ``results/results.json`` is written.

    Grading PrairieLearn's ``/grade`` is refused, as an internal error, unless
    the grader runs as root and can hand compiling and simulating to the
    sandbox user: an image started as another user would let a sketch read
    the tests.

    Args:
        module: A loaded test module, or the path of one.
        grade_dir: PrairieLearn's grading directory.
        work_dir: Where sketches are compiled and simulated.
        sandbox: The sandbox to use; by default one in ``work_dir`` that runs
            as the sandbox user when root.

    Returns:
        The results, also written to ``results.json``.
    """
    grade_dir = Path(grade_dir)
    results = Results()
    try:
        if not isinstance(module, ModuleType):
            module = load_module(module)
        budget = Budget(getattr(module, "TIME_BUDGET_S", DEFAULT_TIME_BUDGET_S))
        if sandbox is None:
            sandbox = Sandbox.default(work_dir)
        if sandbox.user is None and grade_dir == GRADE_DIR:
            raise RuntimeError(
                f"Refusing to grade {GRADE_DIR} without the sandbox user. Run the grader as "
                f"root in its image, so that compiling and simulating can run as {SANDBOX_USER}."
            )
        if sandbox.user and os.geteuid() == 0:
            protect(grade_dir)
        submission = Submission(grade_dir, sketch_file=getattr(module, "SKETCH_FILE", None))
        results = Grading(module, submission, sandbox, budget).run()
    except Exception:
        traceback.print_exc()
        results.gradable = False
        results.add_message(INTERNAL_ERROR_MESSAGE)
    finally:
        results.write(grade_dir)
    return results
