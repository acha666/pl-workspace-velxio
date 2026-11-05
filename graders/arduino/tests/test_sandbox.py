"""The sandbox: who tools run as, the limits they start under, and killing them."""

from __future__ import annotations

import ast
import itertools
import os
import pwd
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from arduinograder.errors import Ungradable
from arduinograder.sandbox import SANDBOX_USER, Budget, Limits, Sandbox
from arduinograder.sim.runner import Session

_runs = itertools.count()


def _can_drop_privileges() -> bool:
    try:
        pwd.getpwnam(SANDBOX_USER)
    except KeyError:
        return False
    return os.geteuid() == 0


@pytest.mark.skipif(not _can_drop_privileges(), reason="needs root and the sandbox user")
def test_tools_run_as_the_sandbox_user_with_its_own_group_only() -> None:
    # The sandbox user must reach the work directory, so keep it out of tmp_path.
    work_dir = Path(f"/tmp/arduinograder-sandbox-{next(_runs)}")
    sandbox = Sandbox.default(work_dir).prepare()
    assert sandbox.user == SANDBOX_USER
    account = pwd.getpwnam(SANDBOX_USER)
    status, output = sandbox.run(["id"], timeout=10)
    assert status == 0 and f"uid={account.pw_uid}({SANDBOX_USER})" in output, output
    groups = re.search(r"groups=(\S+)", output)
    assert groups and groups.group(1) == f"{account.pw_gid}({SANDBOX_USER})", output
    sketch = sandbox.write("sketch/sketch.ino", "void loop() {}")
    assert sketch.stat().st_uid == account.pw_uid and work_dir.stat().st_uid == account.pw_uid
    secret = Path(f"/tmp/arduinograder-secret-{next(_runs)}")
    secret.write_text("x")
    secret.chmod(0o600)
    try:
        status, _ = sandbox.run(["cat", str(secret)], timeout=10)
        assert status != 0, "the sandbox user could read a file hidden from it"
    finally:
        secret.unlink()


def test_a_used_or_linked_work_directory_is_refused(tmp_path: Path) -> None:
    used = tmp_path / "used"
    Sandbox(used).prepare()
    with pytest.raises(ValueError, match="empty"):
        Sandbox(used).prepare()
    (tmp_path / "link").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="symlink"):
        Sandbox(tmp_path / "link").prepare()
    assert sorted(path.name for path in used.iterdir()) == [
        "cache",
        "downloads",
        "home",
        "sketch",
        "user",
    ]


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


def _gone(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return True
    return state == "Z"


def test_a_tool_that_overruns_its_timeout_is_killed_with_its_children(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    started = time.monotonic()
    with pytest.raises(Ungradable):
        Sandbox(tmp_path).run(["sh", "-c", f"sleep 30 & echo $! > {pid_file}; wait"], timeout=0.5)
    assert time.monotonic() - started < 10
    grandchild = int(pid_file.read_text())
    for _ in range(50):
        if _gone(grandchild):
            break
        time.sleep(0.1)
    else:
        pytest.fail("the tool's own child outlived the timeout")


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
