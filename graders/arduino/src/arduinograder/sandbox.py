"""Where, as whom and within what limits the toolchain and the simulator run.

``Sandbox`` is the work directory and the account tools run as; ``Limits``
are the per-process resource limits they start under; ``Budget`` is the
wall-clock time left for all of them together.
"""

from __future__ import annotations

import contextlib
import os
import resource
import shutil
import signal
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .errors import TIMEOUT_MESSAGE, Ungradable

SANDBOX_USER: Final = "sbuser"
"""The unprivileged account that compiles and simulates in the grader image."""


@dataclass(frozen=True)
class Limits:
    """Per-process resource limits a tool starts under.

    They are generous: a sketch that reaches them is far beyond anything a
    question asks for. Their job is to stop one runaway tool before it takes
    the whole grader down with it, and to make the cause show in the tool's
    own output. Children inherit them, so they cover the compilers the
    Arduino CLI starts.

    Attributes:
        cpu_s: CPU seconds a process may use before it is stopped, or ``None``.
            The hard limit, after which it is killed outright, is 10 s more.
        memory_bytes: Address space a process may map, or ``None``. The
            Arduino CLI's Go runtime needs about 1 GiB of it.
        file_bytes: The largest file a process may write, or ``None``.
    """

    cpu_s: int | None = None
    memory_bytes: int | None = None
    file_bytes: int | None = None

    def apply(self) -> None:
        """Set the limits on the current process; meant as a ``preexec_fn``."""
        if self.cpu_s is not None:
            _lower(resource.RLIMIT_CPU, self.cpu_s, self.cpu_s + 10)
        if self.memory_bytes is not None:
            _lower(resource.RLIMIT_AS, self.memory_bytes, self.memory_bytes)
        if self.file_bytes is not None:
            _lower(resource.RLIMIT_FSIZE, self.file_bytes, self.file_bytes)


def _lower(which: int, soft: int, hard: int) -> None:
    """Lower a limit to ``soft`` and ``hard``, within the hard limit already set."""
    _, current_hard = resource.getrlimit(which)
    if current_hard != resource.RLIM_INFINITY:
        hard = min(hard, current_hard)
        soft = min(soft, hard)
    resource.setrlimit(which, (soft, hard))


COMPILER_LIMITS: Final = Limits(cpu_s=10, memory_bytes=1536 << 20, file_bytes=1 << 30)
"""Limits for the Arduino CLI and the compilers it runs.

At 0.9 CPU, 10 CPU seconds leaves room in the default 25 s wall-clock budget
for startup and reporting a runaway compiler as a failed submission.
"""
SIMULATOR_LIMITS: Final = Limits(memory_bytes=1 << 30, file_bytes=256 << 20)
"""Limits for avrsim; the time budget bounds how long it runs."""


class Budget:
    """Wall-clock time left for compiling and simulating.

    Attributes:
        seconds: The budget this started with.
    """

    def __init__(self, seconds: float) -> None:
        """Start a budget of ``seconds`` from now."""
        self.seconds = seconds
        self._deadline = time.monotonic() + seconds

    def remaining(self) -> float:
        """Return the seconds left.

        Raises:
            Ungradable: Once the budget is spent, with the timeout message.
        """
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise Ungradable(TIMEOUT_MESSAGE)
        return remaining


class Sandbox:
    """A work directory and the user to run tools as.

    With a user, the work directory belongs to that user and tools run as it,
    so a sketch compiled there cannot read what the grader (running as root)
    keeps under ``/grade``. Without one, everything runs as the current user,
    for local use and tests.

    Attributes:
        work_dir: The directory that sketches, builds and tool state go in.
        user: The account tools run as, or ``None`` for the current user.
        arduino_data: The Arduino CLI data directory holding the AVR core.
    """

    def __init__(
        self,
        work_dir: str | os.PathLike[str],
        *,
        user: str | None = None,
        arduino_data: str | None = None,
    ) -> None:
        """Describe a sandbox without creating anything yet.

        Args:
            work_dir: A missing or empty work directory; never cleared by ``prepare()``.
            user: The account to run tools as. The grader must then run as root.
            arduino_data: The Arduino CLI data directory; defaults to the
                ``ARDUINO_DIRECTORIES_DATA`` environment variable or
                ``/opt/arduino/data``.
        """
        self.work_dir = Path(work_dir)
        self.user = user
        self.arduino_data = arduino_data or os.environ.get(
            "ARDUINO_DIRECTORIES_DATA", "/opt/arduino/data"
        )

    @classmethod
    def default(cls, work_dir: str | os.PathLike[str]) -> Sandbox:
        """Return a sandbox that uses the sandbox user when root, else the current user."""
        return cls(work_dir, user=SANDBOX_USER if os.geteuid() == 0 else None)

    def prepare(self) -> Sandbox:
        """Create an empty work directory owned by the sandbox user.

        Returns:
            This sandbox, for chaining.

        Raises:
            ValueError: If the work directory is a symlink or is not empty.
        """
        if self.work_dir.is_symlink() or (
            self.work_dir.exists() and (not self.work_dir.is_dir() or any(self.work_dir.iterdir()))
        ):
            raise ValueError(f"Work directory must be empty and not a symlink: {self.work_dir}")
        for name in ["sketch", "home", "user", "downloads", "cache"]:
            (self.work_dir / name).mkdir(parents=True)
        for path in [self.work_dir, *self.work_dir.rglob("*")]:
            self._own(path)
        return self

    def _own(self, path: Path) -> None:
        if self.user:
            shutil.chown(path, self.user, self.user)

    @property
    def env(self) -> dict[str, str]:
        """The environment tools run with: a minimal PATH and Arduino CLI directories."""
        return {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(self.work_dir / "home"),
            "LANG": "C.UTF-8",
            "ARDUINO_DIRECTORIES_DATA": self.arduino_data,
            "ARDUINO_DIRECTORIES_USER": str(self.work_dir / "user"),
            "ARDUINO_DIRECTORIES_DOWNLOADS": str(self.work_dir / "downloads"),
            "ARDUINO_BUILD_CACHE_PATH": str(self.work_dir / "cache"),
            "ARDUINO_UPDATER_ENABLE_NOTIFICATION": "false",
            "ARDUINO_METRICS_ENABLED": "false",
        }

    def path(self, *parts: str) -> Path:
        """Return a path inside the work directory."""
        return self.work_dir.joinpath(*parts)

    def write(self, relative: str, text: str) -> Path:
        """Write a text file into the work directory, owned by the sandbox user.

        Args:
            relative: The path inside the work directory; parents are created.
            text: The file's contents.

        Returns:
            The file's path.
        """
        path = self.path(relative)
        if not path.parent.exists():
            path.parent.mkdir(parents=True)
            self._own(path.parent)
        path.write_text(text, encoding="utf-8")
        self._own(path)
        return path

    def popen(
        self,
        args: Sequence[str],
        *,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
        bufsize: int = -1,
        limits: Limits | None = None,
    ) -> subprocess.Popen[bytes]:
        """Start a tool as the sandbox user in its own process group.

        With a user, the tool runs with that user's primary group only: no
        supplementary group of the grader's root account carries over.

        Args:
            args: The command line.
            stdin: As for ``subprocess.Popen``.
            stdout: As for ``subprocess.Popen``.
            stderr: As for ``subprocess.Popen``.
            bufsize: As for ``subprocess.Popen``.
            limits: Resource limits to apply in the child, if any.

        Returns:
            The running process, with byte streams.
        """
        return subprocess.Popen(
            args,
            cwd=self.work_dir,
            env=self.env,
            start_new_session=True,
            user=self.user,
            group=self.user,
            extra_groups=[] if self.user else None,
            preexec_fn=limits.apply if limits else None,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            bufsize=bufsize,
        )

    def run(
        self, args: Sequence[str], *, timeout: float, limits: Limits | None = None
    ) -> tuple[int, str]:
        """Run a tool to completion.

        Args:
            args: The command line.
            timeout: Seconds to allow before killing it.
            limits: Resource limits to apply in the child, if any.

        Returns:
            The exit status and the combined stdout and stderr text.

        Raises:
            Ungradable: If the tool did not finish within ``timeout``.
        """
        process = self.popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            limits=limits,
        )
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill(process)
            raise Ungradable(TIMEOUT_MESSAGE) from None
        return process.returncode, output.decode("utf-8", "replace")


def kill(process: subprocess.Popen[bytes]) -> None:
    """Kill a process from ``Sandbox.popen`` with everything it started, and reap it."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired, ValueError, OSError):
        process.communicate(timeout=5)
