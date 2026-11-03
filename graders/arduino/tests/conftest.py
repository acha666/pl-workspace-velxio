"""Shared fixtures: a compiler and simulator when the toolchain is installed."""

from __future__ import annotations

import itertools
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypeAlias

import pytest

from arduinograder import Scenario, Session, Trace
from arduinograder.sandbox import Budget, Sandbox
from arduinograder.sim import Simulator
from arduinograder.toolchain import Compiler

ROOT = Path(__file__).resolve().parents[3]
COURSE = ROOT / "course"
_runs = itertools.count()

SimulateFn: TypeAlias = Callable[[str, Scenario], Trace]


class SessionFn(Protocol):
    def __call__(
        self, source: str, *, max_pin_changes: int = ..., max_serial_bytes: int = ...
    ) -> Session: ...


@pytest.fixture
def requires_toolchain() -> None:
    """Skip the test unless the Arduino CLI and avrsim are installed."""
    for tool in ("arduino-cli", "avrsim"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} is not installed")


@pytest.fixture
def toolchain(requires_toolchain: None) -> tuple[Compiler, Simulator]:
    """A prepared Sandbox with a Compiler and a Simulator on a generous budget."""
    # The sandbox user must reach the work directory, so keep it out of tmp_path.
    sandbox = Sandbox.default(Path(f"/tmp/arduinograder-test-{next(_runs)}")).prepare()
    budget = Budget(120)
    return Compiler(sandbox, budget), Simulator(sandbox, budget)


@pytest.fixture
def simulate(toolchain: tuple[Compiler, Simulator]) -> SimulateFn:
    """Compile a sketch and run it through a scenario."""
    compiler, simulator = toolchain

    def run(source: str, scenario: Scenario) -> Trace:
        return simulator.run(compiler.compile(source), scenario)

    return run


@pytest.fixture
def session(toolchain: tuple[Compiler, Simulator]) -> SessionFn:
    """Compile a sketch and start it in a Session."""
    compiler, simulator = toolchain

    def start(
        source: str, *, max_pin_changes: int = 200_000, max_serial_bytes: int = 65_536
    ) -> Session:
        return simulator.session(
            compiler.compile(source),
            max_pin_changes=max_pin_changes,
            max_serial_bytes=max_serial_bytes,
        )

    return start
