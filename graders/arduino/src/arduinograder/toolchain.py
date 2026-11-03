"""Compiling sketches for the Uno with the Arduino CLI."""

from __future__ import annotations

import itertools
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .errors import StopGrading
from .sandbox import COMPILER_LIMITS, Budget, Limits, Sandbox

MAX_COMPILE_LOG: Final = 4000
"""Characters of compiler output shown to the student at most."""
MAX_ERRORS: Final = 20
"""Errors after which the compiler stops: the first ones matter, and the log stays short."""
NOISE: Final = re.compile(
    r"^(Sketch uses|Global variables use|Used platform|Used library|arduino:avr|"
    r"Error during build|exit status|Please submit a full bug report|"
    r"with preprocessed source if appropriate|See <https://gcc\.gnu\.org/bugs/>)"
)
"""Lines of compiler output that tell the student nothing, dropped from the log."""
LIMIT_HIT: Final = re.compile(
    r"CPU time limit exceeded|out of memory allocating|virtual memory exhausted|"
    r"File size limit exceeded|Killed \(program"
)
"""Compiler output that means a resource limit stopped it."""
COMPILE_FAILED_MESSAGE: Final = "Your sketch did not compile."
"""Shown above the log when the compiler reported errors."""
LIMIT_MESSAGE: Final = (
    "Compiling your sketch needed more time or memory than the grader allows, so the "
    "compiler was stopped. Simplify the sketch."
)
"""Shown above the log when a resource limit stopped the compiler."""


class CompileError(StopGrading):
    """The sketch did not compile; grading stops with score 0 and the log.

    Attributes:
        log: The cleaned compiler output.
    """

    def __init__(self, log: str, *, message: str = COMPILE_FAILED_MESSAGE) -> None:
        """Wrap a cleaned compiler log in the message students see."""
        super().__init__(message + "\n\n" + log)
        self.log = log


@dataclass(frozen=True)
class Firmware:
    """A compiled sketch.

    Attributes:
        path: The ELF file to simulate.
        log: The cleaned compiler output.
    """

    path: Path
    log: str


class Compiler:
    """Compiles sketches in a sandbox within a time budget.

    Attributes:
        sandbox: Where the Arduino CLI runs.
        budget: The wall-clock budget each compilation draws on.
        fqbn: The Arduino CLI board name.
        limits: The resource limits the Arduino CLI and the compilers run under.
    """

    FQBN: Final = "arduino:avr:uno"

    def __init__(
        self,
        sandbox: Sandbox,
        budget: Budget,
        *,
        fqbn: str = FQBN,
        limits: Limits = COMPILER_LIMITS,
    ) -> None:
        """Bind a compiler to a sandbox and a budget."""
        self.sandbox = sandbox
        self.budget = budget
        self.fqbn = fqbn
        self.limits = limits
        self._builds = itertools.count()

    def compile(self, source: str, *, name: str = "sketch.ino") -> Firmware:
        """Compile a sketch.

        Args:
            source: The sketch's text.
            name: The student's file name, shown in place of the work path in
                compiler messages.

        Returns:
            The compiled firmware.

        Raises:
            CompileError: If the sketch did not compile or hit a resource limit.
            Ungradable: If the compiler overran the time budget.
            RuntimeError: If the Arduino CLI succeeded without producing an ELF.
        """
        sketch = self.sandbox.write("sketch/sketch.ino", source)
        build = self.sandbox.path("build")
        status, log = self.sandbox.run(
            [
                "arduino-cli", "compile", "--no-color", "--jobs", "1", "--fqbn", self.fqbn,
                "--build-property", f"compiler.cpp.extra_flags=-fmax-errors={MAX_ERRORS}",
                "--build-property", f"compiler.c.extra_flags=-fmax-errors={MAX_ERRORS}",
                "--build-path", str(build), str(sketch.parent),
            ],
            timeout=self.budget.remaining(),
            limits=self.limits,
        )  # fmt: skip
        log = self._clean(log, sketch, name)
        if status != 0:
            message = LIMIT_MESSAGE if LIMIT_HIT.search(log) else COMPILE_FAILED_MESSAGE
            raise CompileError(log, message=message)
        firmware = build / "sketch.ino.elf"
        if not firmware.is_file():
            raise RuntimeError(f"arduino-cli produced no firmware:\n{log}")
        # The next compilation reuses the build directory, so keep this
        # firmware apart from it: a test may compile a reference sketch too.
        kept = self.sandbox.path(f"firmware-{next(self._builds)}.elf")
        shutil.copyfile(firmware, kept)
        return Firmware(kept, log)

    def _clean(self, log: str, sketch: Path, name: str) -> str:
        """Strip colours, work paths and build statistics from compiler output."""
        log = re.sub(r"\x1b\[[0-9;]*m", "", log)
        log = log.replace(str(sketch), name).replace(str(self.sandbox.work_dir), "")
        lines = [line for line in log.splitlines() if line.strip() and not NOISE.match(line)]
        text = "\n".join(lines)
        if len(text) > MAX_COMPILE_LOG:
            text = text[:MAX_COMPILE_LOG] + "\n[compiler output truncated]"
        return text
