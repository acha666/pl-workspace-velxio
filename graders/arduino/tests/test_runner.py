"""Sessions over the avrsim protocol, against a scripted stand-in for avrsim."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arduinograder import PinState, Scenario, SimulationStopped
from arduinograder.sandbox import Budget, Sandbox
from arduinograder.sim import Session, Simulator

FAKE = Path(__file__).with_name("fake_avrsim.py")


def fake_avrsim(directory: Path, script: str) -> tuple[Path, Path]:
    """Return a program that runs the fake on ``script``, and the log of its commands."""
    directory.mkdir(exist_ok=True)
    script_file, log = directory / "script.txt", directory / "commands.log"
    script_file.write_text(script)
    program = directory / "avrsim"
    program.write_text(f'#!/bin/sh\nexec {sys.executable} {FAKE} {script_file} {log} "$@"\n')
    program.chmod(0o755)
    return program, log


def start(
    directory: Path, script: str, *, max_pin_changes: int = 200_000, max_serial_bytes: int = 65_536
) -> tuple[Session, Path]:
    program, log = fake_avrsim(directory, script)
    simulator = Simulator(Sandbox(directory / "work").prepare(), Budget(30), program=str(program))
    session = simulator.session(
        "firmware.elf", max_pin_changes=max_pin_changes, max_serial_bytes=max_serial_bytes
    )
    return session, log


SCRIPT = """
P 0 13 I
P 16000 13 L
P 32000 13 H
S 48000 104
S 64000 105
S 80000 10
P 160000 13 L
P 400000 13 H
DONE 800000 done
"""


def test_a_session_drives_the_program_over_the_protocol(tmp_path: Path) -> None:
    session, log = start(tmp_path, SCRIPT, max_pin_changes=50, max_serial_bytes=9)
    with session as run:
        assert run.run_until(5) and run.now_ms == 5 and run.state(13) is PinState.HIGH
        run.set(2, "HIGH")
        run.analog("A0", 512)
        run.send("ok")
        run.release(2)
        assert run.pulse(3, 0, duration_ms=5) and run.now_ms == 10
        assert run.run_for(5) and run.now_ms == 15
        assert run.wait_for(13, 1, timeout_ms=0) is None, "before the input: no reaction"
        assert run.wait_for(13, "LOW", timeout_ms=0) == 10
        assert run.wait_for(13, "HIGH", timeout_ms=20) == 25 and run.now_ms == 25
        assert run.wait_for_line(timeout_ms=0) is None, "the line was complete before the input"
        assert not run.run_until(100) and run.now_ms == 50 and run.stop_reason == "done"
        assert not run.run_for(10) and run.now_ms == 50
        trace = run.trace
    assert trace.pin(13).edges().times_ms == [2, 10, 25] and trace.serial.text() == "hi\n"
    assert trace.stop_reason == "done" and trace.end_ms == 50
    with pytest.raises(SimulationStopped, match="stopped running at 50 ms"):
        trace.pin(13).at(60)
    assert log.read_text().splitlines() == [
        "limit pins 50",
        "limit serial 9",
        "run 80000",
        "set 2 1",
        "analog 0 512",
        "send 6f6b",
        "release 2",
        "set 3 0",
        "run 160000",
        "release 3",
        "run 240000",
        "run 560000 until P 13",
        "run 1600000",
    ]


def test_send_is_chunked_and_an_input_keeps_a_line_in_progress(tmp_path: Path) -> None:
    script = "S 16000 104\nS 32000 105\nS 48000 10\nS 64000 33\nS 96000 10\n"
    session, log = start(tmp_path, script)
    data = bytes(range(256)) * 2 + b"xyz"
    with session as run:
        assert run.run_until(5)
        run.send(data)
        assert run.wait_for_line(timeout_ms=10) == (6, "!")
    commands = log.read_text().splitlines()
    sends = [command[5:] for command in commands if command.startswith("send ")]
    assert [len(bytes.fromhex(chunk)) for chunk in sends] == [256, 256, 3]
    assert bytes.fromhex("".join(sends)) == data
    assert commands[-1] == "run 240000 until S 10"


def test_avrsim_failures_are_reported(tmp_path: Path) -> None:
    session, _ = start(tmp_path / "dies", "DIE simavr: cannot load firmware\n")
    with session as run, pytest.raises(RuntimeError, match="status 3: simavr: cannot load"):
        run.run_until(1)
    for directory, reply, error in [
        ("garbage", "X 0 nonsense", "Unexpected avrsim reply"),
        ("reason", "T 0 vanished", "Unexpected avrsim stop reason"),
    ]:
        session, _ = start(tmp_path / directory, f"GARBAGE {reply}\n")
        with session as run, pytest.raises(RuntimeError, match=error):
            run.run_until(1)


def test_the_simulator_applies_scenario_events_at_their_times(tmp_path: Path) -> None:
    program, log = fake_avrsim(tmp_path, "P 0 13 I\nP 800000 13 H\nDONE 2400000 crashed\n")
    simulator = Simulator(Sandbox(tmp_path / "work").prepare(), Budget(30), program=str(program))
    scenario = (
        Scenario(duration_ms=200, max_pin_changes=7, max_serial_bytes=8)
        .pulse(2, 1, at_ms=10, duration_ms=20)
        .analog("A1", 3, at_ms=40)
        .send("go", at_ms=40)
        .set(3, "LOW", at_ms=180)
    )
    trace = simulator.run("firmware.elf", scenario)
    assert trace.stop_reason == "crashed" and trace.end_ms == 150
    assert trace.pin(13).at(60).is_high and trace.max_pin_changes == 7
    with pytest.raises(SimulationStopped, match="crashed at 150 ms"):
        trace.pin(13).at(151)
    assert log.read_text().splitlines() == [
        "limit pins 7",
        "limit serial 8",
        "run 160000",
        "set 2 1",
        "run 480000",
        "release 2",
        "run 640000",
        "analog 1 3",
        "send 676f",
        "run 2880000",
    ]
