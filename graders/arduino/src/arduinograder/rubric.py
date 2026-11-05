"""Test functions with points, each run on its own, and what they scored.

A question's test module marks functions with the decorators here; each test
receives the fixtures it names as parameters and is scored by itself, so one
failing or broken test never affects the others.
"""

from __future__ import annotations

import inspect
import math
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from types import FunctionType, ModuleType
from typing import Final, Protocol, TypeAlias, TypedDict, TypeVar

from .errors import ConfigurationError, StopGrading, Ungradable
from .sim import Scenario, SimulationStopped

GRADER_ERROR_MESSAGE: Final = (
    "This test could not be run because of an error in the grader. Tell your instructor."
)
"""Shown for a test that raised an unexpected error."""
ITEM_ATTR: Final = "_arduinograder_item"
"""The attribute the decorators keep an ``ItemSpec`` under on a test function."""
GATE_ATTR: Final = "_arduinograder_gate"
"""The attribute ``gate()`` sets on a gate function."""

F = TypeVar("F", bound=Callable[..., object])
TestFunction: TypeAlias = Callable[..., object]
"""A test or gate: any function whose parameters name fixtures."""


class Resolver(Protocol):
    """Supplies fixtures by name to the test or gate being run."""

    def __call__(self, name: str, item: Item | None = None, /) -> object:
        """Return the fixture called ``name``, for ``item`` if a test is running."""
        ...


class TestResultDict(TypedDict):
    """One entry of ``tests`` in PrairieLearn's ``results.json``."""

    name: str
    description: str
    points: float
    max_points: float
    message: str


@dataclass
class ItemSpec:
    """What the decorators record on a test function.

    Attributes:
        points: What the test is worth; 0 until ``points()`` sets it.
        name: The name shown to students, or ``None`` for one made from the function name.
        description: The description shown to students.
        scenario: The test's own scenario for the ``trace`` fixture, if any.
    """

    points: float = 0
    name: str | None = None
    description: str = ""
    scenario: Scenario | None = None


def _spec(func: Callable[..., object]) -> ItemSpec:
    """Return the function's ``ItemSpec``, attaching an empty one first if needed."""
    spec = getattr(func, ITEM_ATTR, None)
    if not isinstance(spec, ItemSpec):
        spec = ItemSpec()
        setattr(func, ITEM_ATTR, spec)
    return spec


def points(value: float) -> Callable[[F], F]:
    """Make a function a test worth ``value`` points.

    It receives the fixtures it names as parameters and passes unless it raises
    ``AssertionError`` or its ``check`` records a failure; returning a number from
    0 to 1 awards that fraction of the points instead.
    """

    def decorate(func: F) -> F:
        _spec(func).points = value
        return func

    return decorate


def name(text: str) -> Callable[[F], F]:
    """Set the test's name shown to students; by default it comes from the function name."""

    def decorate(func: F) -> F:
        _spec(func).name = text
        return func

    return decorate


def description(text: str) -> Callable[[F], F]:
    """Set the test's description shown to students."""

    def decorate(func: F) -> F:
        _spec(func).description = text
        return func

    return decorate


def with_scenario(scenario: Scenario) -> Callable[[F], F]:
    """Give this test's ``trace`` fixture its own scenario instead of the module's."""

    def decorate(func: F) -> F:
        _spec(func).scenario = scenario
        return func

    return decorate


def gate(func: F) -> F:
    """Make a function a gate, run before the tests to reject a submission.

    It takes fixtures like a test and stops grading with zero points by raising
    ``StopGrading``, returning a message or failing an ``assert``.
    """
    setattr(func, GATE_ATTR, True)
    return func


class Check:
    """Expectations within one test; every failure's message goes to the student.

    Attributes:
        failures: The messages of the checks that failed, in order.
        total: How many checks were made.
    """

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.total = 0

    def __call__(self, condition: object, message: str) -> bool:
        """Record whether a condition holds.

        Args:
            condition: What should be true.
            message: Shown to the student if it is not; anything else is
                converted to text.

        Returns:
            The condition as a bool, so a test can stop early.
        """
        self.total += 1
        if not condition:
            self.failures.append(str(message))
        return bool(condition)

    def fail(self, message: str) -> None:
        """Record a failure outright."""
        self.total += 1
        self.failures.append(str(message))

    @property
    def ok(self) -> bool:
        """Whether every check passed."""
        return not self.failures

    @property
    def passed(self) -> int:
        """How many checks passed."""
        return self.total - len(self.failures)

    @property
    def fraction(self) -> float:
        """Passed checks over all checks, for partial credit; 1 with no checks."""
        return self.passed / self.total if self.total else 1.0


@dataclass
class Item:
    """A test to run.

    Attributes:
        func: The test function.
        name: Its name shown to students.
        points: What it is worth.
        description: Its description shown to students.
        scenario: Its own scenario for the ``trace`` fixture, if any.
    """

    func: TestFunction
    name: str
    points: float
    description: str = ""
    scenario: Scenario | None = None


@dataclass
class ItemResult:
    """What a test scored.

    Attributes:
        name: The test's name.
        points: The points awarded.
        max_points: The points the test was worth.
        description: The test's description.
        message: Feedback for the student, usually the failed checks' messages.
    """

    name: str
    points: float
    max_points: float
    description: str = ""
    message: str = ""

    def to_dict(self) -> TestResultDict:
        """Return the entry for PrairieLearn's ``results.json``."""
        return {
            "name": self.name,
            "description": self.description,
            "points": self.points,
            "max_points": self.max_points,
            "message": self.message,
        }


def collect(module: ModuleType) -> tuple[list[TestFunction], list[Item]]:
    """Return the gates and tests a module defines, in definition order.

    Gates come from the module's optional ``gates`` list, then from functions
    decorated with ``gate()``; tests from functions decorated with ``points()``.
    """
    gates: list[TestFunction] = list(getattr(module, "gates", None) or [])
    items: list[Item] = []
    functions = [
        value
        for value in vars(module).values()
        if isinstance(value, FunctionType)
        and (hasattr(value, ITEM_ATTR) or hasattr(value, GATE_ATTR))
    ]
    functions.sort(key=lambda func: func.__code__.co_firstlineno)
    for func in functions:
        if hasattr(func, GATE_ATTR):
            gates.append(func)
        spec = getattr(func, ITEM_ATTR, None)
        if isinstance(spec, ItemSpec):
            items.append(
                Item(
                    func,
                    str(spec.name) if spec.name else _default_name(func),
                    spec.points,
                    str(spec.description),
                    spec.scenario,
                )
            )
    return gates, items


def _default_name(func: FunctionType) -> str:
    """Return a name for students from the function name: ``test_led_on`` is ``"Led on"``."""
    text = func.__name__
    if text.startswith("test_"):
        text = text[5:]
    text = text.replace("_", " ").strip()
    return (text[:1].upper() + text[1:]) if text else func.__name__


def call_with_fixtures(func: TestFunction, resolve: Callable[[str], object]) -> object:
    """Call a function with each parameter filled by ``resolve(name)``."""
    return func(**{param: resolve(param) for param in inspect.signature(func).parameters})


def run_gate(func: TestFunction, resolve: Resolver) -> None:
    """Run a gate.

    Raises:
        StopGrading: If the gate raised it, returned a message, failed an ``assert``
            or asked about a time after the simulation stopped.
    """
    try:
        message = call_with_fixtures(func, resolve)
    except AssertionError as error:
        raise StopGrading(str(error) or "A check failed.") from None
    except SimulationStopped as stopped:
        raise StopGrading(str(stopped)) from None
    if message:
        raise StopGrading(str(message))


def run_item(item: Item, resolve: Resolver) -> ItemResult:
    """Run one test on its own and return its result.

    ``StopGrading``, ``Ungradable`` and ``ConfigurationError`` propagate; any other
    exception fails only this test. A failed assert's message, a
    ``SimulationStopped`` explanation and every failed check go to the student.

    Args:
        item: The test to run.
        resolve: Supplies the fixtures it names, except ``check``, made here.
    """
    check = Check()

    def resolve_for_item(param: str) -> object:
        return check if param == "check" else resolve(param, item)

    try:
        outcome = call_with_fixtures(item.func, resolve_for_item)
        fraction = _fraction(outcome, check)
    except (StopGrading, Ungradable, ConfigurationError):
        raise
    except AssertionError as error:
        check.fail(str(error) or "A check failed.")
        fraction = 0.0
    except SimulationStopped as stopped:
        check.fail(str(stopped))
        fraction = 0.0
    except Exception:
        traceback.print_exc()
        return ItemResult(item.name, 0, item.points, item.description, GRADER_ERROR_MESSAGE)
    # Unrounded: rounded points over unrounded max_points could put full
    # marks at 1.0003, which PrairieLearn rejects, or at 0.9999.
    return ItemResult(
        item.name,
        item.points * fraction,
        item.points,
        item.description,
        "\n".join(check.failures),
    )


def _fraction(outcome: object, check: Check) -> float:
    """Return the share of points a test earned from what it returned and checked."""
    if outcome is None:
        return 1.0 if check.ok else 0.0
    if isinstance(outcome, bool):
        return 1.0 if outcome else 0.0
    if isinstance(outcome, int | float) and math.isfinite(outcome):
        return min(max(float(outcome), 0.0), 1.0)
    raise TypeError(f"A test must return None, a bool or a fraction, not {outcome!r}.")
