"""Grade Arduino Uno sketches by compiling them and simulating their inputs.

A question's ``tests/test.py`` defines test functions worth points::

    import arduinograder as ag

    scenario = ag.Scenario(duration_ms=1000)

    @ag.points(2)
    def test_led_on(trace):
        assert trace.pin(13).at(500).is_high, "The LED should be on at 500 ms."

Tests name the fixtures they need as parameters: ``trace``, ``simulate``,
``session``, ``firmware``, ``source``, ``check`` and more; see the grader
README. Helpers for particular question designs are in
``arduinograder.extras``.
"""

from .board import HIGH, LOW, pin_number
from .cli import main
from .errors import StopGrading, Ungradable
from .grading import grade
from .pl import Results, Submission
from .rubric import Check, description, gate, name, points, with_scenario
from .sim import (
    Change,
    Edge,
    Edges,
    Line,
    PinState,
    PinTrace,
    Scenario,
    SerialTrace,
    Session,
    SimulationStopped,
    Trace,
)
from .toolchain import CompileError, Firmware

__all__ = [
    "HIGH",
    "LOW",
    "Change",
    "Check",
    "CompileError",
    "Edge",
    "Edges",
    "Firmware",
    "Line",
    "PinState",
    "PinTrace",
    "Results",
    "Scenario",
    "SerialTrace",
    "Session",
    "SimulationStopped",
    "StopGrading",
    "Submission",
    "Trace",
    "Ungradable",
    "description",
    "gate",
    "grade",
    "main",
    "name",
    "pin_number",
    "points",
    "with_scenario",
]
