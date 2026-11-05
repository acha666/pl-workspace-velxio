"""Compiling: the command, the cleaned log and the firmware kept, without the Arduino CLI."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from arduinograder.errors import Ungradable
from arduinograder.sandbox import Budget, Limits, Sandbox
from arduinograder.toolchain import (
    COMPILE_FAILED_MESSAGE,
    MAX_COMPILE_LOG,
    MAX_ERRORS,
    CompileError,
    Compiler,
)


class FakeSandbox(Sandbox):
    """A sandbox whose Arduino CLI is a canned reply, recording what it was asked."""

    def __init__(self, work_dir: Path) -> None:
        super().__init__(work_dir)
        self.commands: list[list[str]] = []
        self.replies: list[tuple[int, str, bool]] = []

    def run(
        self, args: Sequence[str], *, timeout: float, limits: Limits | None = None
    ) -> tuple[int, str]:
        self.commands.append(list(args))
        status, log, produces_elf = self.replies.pop(0)
        elf = self.path("build/sketch.ino.elf")
        elf.parent.mkdir(exist_ok=True)
        if produces_elf:
            elf.write_bytes(b"\x7fELF")
        else:
            elf.unlink(missing_ok=True)
        return status, log


def test_compile_errors_are_cleaned_and_name_the_submitted_file(tmp_path: Path) -> None:
    sandbox = FakeSandbox(tmp_path / "work")
    sandbox.prepare()
    compiler = Compiler(sandbox, Budget(60))
    sketch = sandbox.path("sketch/sketch.ino")
    sandbox.replies = [
        (
            1,
            f"\x1b[1m{sketch}:2:3: \x1b[31merror:\x1b[0m 'oops' was not declared\n"
            f"   in {sandbox.work_dir}/build/sketch.ino.cpp\n"
            "Used platform Version Path\n"
            "\n"
            "Error during build: exit status 1\n",
            False,
        )
    ]
    with pytest.raises(CompileError) as error:
        compiler.compile("void loop() { oops }", name="lab.ino")
    assert str(error.value) == COMPILE_FAILED_MESSAGE + "\n\n" + error.value.log
    assert error.value.log == (
        "lab.ino:2:3: error: 'oops' was not declared\n   in /build/sketch.ino.cpp"
    )
    assert sketch.read_text() == "void loop() { oops }"
    [command] = sandbox.commands
    assert command[:2] == ["arduino-cli", "compile"] and command[-1] == str(sketch.parent)
    assert command[command.index("--fqbn") + 1] == Compiler.FQBN
    assert f"-fmax-errors={MAX_ERRORS}" in " ".join(command)


def test_a_compile_stopped_by_a_limit_is_explained_and_long_logs_are_cut(tmp_path: Path) -> None:
    sandbox = FakeSandbox(tmp_path / "work")
    sandbox.prepare()
    compiler = Compiler(sandbox, Budget(60))
    sandbox.replies = [(1, "cc1plus: out of memory allocating 1 bytes\n" + "x" * 10_000, False)]
    with pytest.raises(CompileError, match="more time or memory") as error:
        compiler.compile("void loop() {}")
    assert error.value.log.startswith("cc1plus: out of memory")
    assert error.value.log.endswith("[compiler output truncated]")
    assert len(error.value.log) < MAX_COMPILE_LOG + 50
    with pytest.raises(Ungradable):
        Compiler(sandbox, Budget(0)).compile("void loop() {}")


def test_each_firmware_is_kept_and_a_missing_one_is_an_error(tmp_path: Path) -> None:
    sandbox = FakeSandbox(tmp_path / "work")
    sandbox.prepare()
    compiler = Compiler(sandbox, Budget(60))
    sandbox.replies = [(0, "Sketch uses 924 bytes\n", True), (0, "", True), (0, "", False)]
    first = compiler.compile("void loop() { a(); }")
    second = compiler.compile("void loop() { b(); }")
    assert first.path != second.path and first.path.is_file() and second.path.is_file()
    assert first.log == "", "build statistics are noise"
    assert sandbox.path("sketch/sketch.ino").read_text() == "void loop() { b(); }"
    with pytest.raises(RuntimeError, match="no firmware"):
        compiler.compile("void loop() {}")
