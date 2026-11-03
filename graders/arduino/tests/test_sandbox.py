"""The sandbox: who tools run as, the limits they start under, and killing them."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from arduinograder.errors import Ungradable
from arduinograder.sandbox import COMPILER_LIMITS, Budget, Limits, Sandbox
from arduinograder.sim.runner import Session


def test_popen_drops_privileges_fully_and_applies_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []

    class FakePopen:
        def __init__(self, args: list[str], **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    Sandbox(tmp_path, user="sbuser").popen(["true"])
    Sandbox(tmp_path).popen(["true"], limits=COMPILER_LIMITS)
    sandboxed, local = calls
    assert sandboxed["user"] == sandboxed["group"] == "sbuser"
    assert sandboxed["extra_groups"] == [] and sandboxed["preexec_fn"] is None
    assert sandboxed["start_new_session"] and sandboxed["cwd"] == tmp_path
    assert local["user"] is None and local["extra_groups"] is None
    assert local["preexec_fn"] == COMPILER_LIMITS.apply


def test_limits_reach_the_tool(tmp_path: Path) -> None:
    limits = Limits(cpu_s=100, memory_bytes=1 << 30, file_bytes=1 << 20)
    status, output = Sandbox(tmp_path).run(
        [
            sys.executable,
            "-c",
            "import resource as r; print([r.getrlimit(w) for w in "
            "(r.RLIMIT_CPU, r.RLIMIT_AS, r.RLIMIT_FSIZE)])",
        ],
        timeout=30,
        limits=limits,
    )
    assert status == 0, output
    cpu, memory, file = ast.literal_eval(output)
    assert cpu[0] == min(100, cpu[1]) and cpu[1] <= 110
    assert memory[0] == min(1 << 30, memory[1]) and file[0] == min(1 << 20, file[1])


def test_a_spent_budget_kills_the_simulator(tmp_path: Path) -> None:
    process = Sandbox(tmp_path).popen(
        ["sleep", "30"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    session = Session(process, Budget(0), max_pin_changes=1, max_serial_bytes=1)
    with pytest.raises(Ungradable):
        session.run_until(1)
    assert process.poll() is not None
    session.close()
