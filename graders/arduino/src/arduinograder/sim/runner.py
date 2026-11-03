"""Running firmware in avrsim: open loop through a Scenario, or step by step."""

from __future__ import annotations

import contextlib
import os
import select
import subprocess
from collections.abc import Callable
from typing import Final, Literal, TypeAlias, cast, get_args

from ..board import ANALOG_PINS, NUM_PINS, PinLike, pin_number, to_cycles, to_ms
from ..errors import TIMEOUT_MESSAGE, Ungradable
from ..sandbox import SIMULATOR_LIMITS, Budget, Sandbox, kill
from ..toolchain import Firmware
from .scenario import Scenario
from .trace import STATE_CODES, Line, PinState, Record, RecordKind, Trace

FinalReason: TypeAlias = Literal["done", "crashed", "pin-limit", "serial-limit"]
"""Why a program stops for good."""
RunReason: TypeAlias = Literal["reached", "watched", "done", "crashed", "pin-limit", "serial-limit"]
"""Why a ``run`` command ended: the target cycle, a watched record, or a final reason."""
Watch: TypeAlias = tuple[RecordKind, int] | None
"""What a run stops early for: a record kind and key, such as ``("P", 13)``, or nothing."""
NEWLINE: Final = ord("\n")
StateLike: TypeAlias = PinState | str | int | None
"""A pin state as a ``PinState``, its name, or a level."""

FINAL_REASONS: Final[frozenset[str]] = frozenset(get_args(FinalReason))
RUN_REASONS: Final[frozenset[str]] = frozenset(get_args(RunReason))
SEND_CHUNK: Final = 256
"""Bytes per ``send`` command, keeping lines within avrsim's limit."""


class Simulator:
    """Runs firmware in avrsim as the sandbox user, within the time budget.

    Attributes:
        sandbox: Where avrsim runs.
        budget: The wall-clock budget each run draws on.
        program: The avrsim executable.
    """

    def __init__(self, sandbox: Sandbox, budget: Budget, *, program: str = "avrsim") -> None:
        """Bind a simulator to a sandbox and a budget."""
        self.sandbox = sandbox
        self.budget = budget
        self.program = program

    def run(self, firmware: Firmware | str | os.PathLike[str], scenario: Scenario) -> Trace:
        """Run firmware from reset through a scenario.

        Args:
            firmware: The compiled sketch, or the path of an ELF file.
            scenario: The inputs to apply and how long to run.

        Returns:
            The trace of the whole run.

        Raises:
            Ungradable: If the simulation overran the time budget.
            RuntimeError: If avrsim failed.
        """
        with self.session(
            firmware,
            max_pin_changes=scenario.max_pin_changes,
            max_serial_bytes=scenario.max_serial_bytes,
        ) as session:
            for event in scenario.events:
                if not session._run_to(event.cycle):
                    break
                event.apply(session)
            session._run_to(to_cycles(scenario.duration_ms))
            return session.trace

    def session(
        self,
        firmware: Firmware | str | os.PathLike[str],
        *,
        max_pin_changes: int = 200_000,
        max_serial_bytes: int = 65_536,
    ) -> Session:
        """Start firmware from reset in a session to drive step by step.

        Args:
            firmware: The compiled sketch, or the path of an ELF file.
            max_pin_changes: Stop for good once the program has changed its
                pins this many times.
            max_serial_bytes: Stop for good once the program has sent this
                many bytes.

        Returns:
            The session, to use as a context manager.
        """
        path = firmware.path if isinstance(firmware, Firmware) else firmware
        process = self.sandbox.popen(
            [self.program, str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            limits=SIMULATOR_LIMITS,
        )
        return Session(
            process,
            self.budget,
            max_pin_changes=max_pin_changes,
            max_serial_bytes=max_serial_bytes,
        )


def _as_state(state: StateLike) -> PinState | None:
    """Return the ``PinState`` for a state given by name or level, or ``None`` for any."""
    if state is None or isinstance(state, PinState):
        return state
    if isinstance(state, str):
        return PinState[state.upper()]
    return PinState.HIGH if state else PinState.LOW


def _as_run_reason(text: str) -> RunReason:
    """Return the ``RunReason`` for the word in a ``T`` reply, or raise ``RuntimeError``."""
    if text not in RUN_REASONS:
        raise RuntimeError(f"Unexpected avrsim stop reason: {text!r}")
    return cast(RunReason, text)


class Session:
    """A program running from reset, driven one step at a time.

    Simulated time advances only in ``run_until()``, ``run_for()``,
    ``pulse()`` and the ``wait_for`` methods; ``set()``, ``release()``,
    ``analog()`` and ``send()`` apply at the current time. Once the program is
    done, crashed or over a limit, ``running`` is ``False`` and time no longer
    advances. Use it as a context manager, or call ``close()``.

    What the program does is recorded as it runs, and the ``wait_for``
    methods hand out those records in order: each returns the first change
    of its pin, or the first Serial line, not returned before, running the
    program further only when there is none yet. An input, through ``set()``,
    ``analog()``, ``send()`` or ``pulse()``, starts afresh: what the program
    did before it is not a reaction to it, so the waits skip that. A
    ``release()`` ends an input rather than starting one, so it does not.

    Attributes:
        max_pin_changes: The pin change limit in force.
        max_serial_bytes: The Serial byte limit in force.
        stop_reason: Why the program stopped for good, or ``None`` while it runs.
    """

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        budget: Budget,
        *,
        max_pin_changes: int,
        max_serial_bytes: int,
    ) -> None:
        """Take over an avrsim process; use ``Simulator.session()`` instead."""
        self._process = process
        self._budget = budget
        self.max_pin_changes = max_pin_changes
        self.max_serial_bytes = max_serial_bytes
        self._records: list[Record] = []
        self._latest: dict[int, PinState] = {pin: PinState.INPUT for pin in range(NUM_PINS)}
        # Cursors into _records: where the records start that may be reactions
        # to the latest input; per record kind and key, where those start that
        # no wait has returned; and where the first unreturned Serial line starts.
        self._since = 0
        self._consumed: dict[tuple[RecordKind, int], int] = {}
        self._line_start = 0
        self._cycle = 0
        self._buffer = b""
        self.stop_reason: FinalReason | None = None
        self._command(f"limit pins {max_pin_changes}")
        self._command(f"limit serial {max_serial_bytes}")

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """End the session and the avrsim process."""
        if self._process.poll() is None:
            try:
                if self._process.stdin is not None:
                    self._process.stdin.close()
                self._process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                kill(self._process)
        for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()

    # -- Protocol ---------------------------------------------------------------

    def _died(self) -> None:
        """Raise ``RuntimeError`` with avrsim's exit status and stderr once it has exited."""
        error = ""
        if self._process.stderr is not None:
            with contextlib.suppress(OSError):
                error = self._process.stderr.read().decode("utf-8", "replace").strip()
        status = self._process.wait()
        raise RuntimeError(f"avrsim exited with status {status}: {error or 'no message'}")

    def _command(self, text: str) -> None:
        """Send one command line to avrsim."""
        stdin = self._process.stdin
        if stdin is None:
            raise RuntimeError("The avrsim process has no stdin.")
        data = (text + "\n").encode("utf-8")
        try:
            while data:
                data = data[stdin.write(data) :]
        except BrokenPipeError:
            self._died()

    def _readline(self) -> str:
        """Read one reply line, within the time budget."""
        stdout = self._process.stdout
        if stdout is None:
            raise RuntimeError("The avrsim process has no stdout.")
        fd = stdout.fileno()
        while b"\n" not in self._buffer:
            try:
                ready, _, _ = select.select([fd], [], [], self._budget.remaining())
            except Ungradable:
                kill(self._process)
                raise
            if not ready:
                kill(self._process)
                raise Ungradable(TIMEOUT_MESSAGE)
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                self._died()
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return line.decode("utf-8", "replace")

    def _run(self, cycle: int, watch: Watch = None) -> RunReason:
        """Run until a cycle, or until the program produces a watched record."""
        if self.stop_reason is not None:
            return self.stop_reason
        if cycle <= self._cycle:
            return "reached"
        command = f"run {cycle}"
        if watch is not None:
            command += f" until {watch[0]} {watch[1]}"
        self._command(command)
        while True:
            kind, at_text, *rest = self._readline().split()
            at = int(at_text)
            if kind == "P":
                pin, state = int(rest[0]), STATE_CODES[rest[1]]
                self._records.append(Record(at, "P", pin, state))
                self._latest[pin] = state
            elif kind == "S":
                self._records.append(Record(at, "S", 0, int(rest[0])))
            elif kind == "T":
                reason = _as_run_reason(rest[0])
                self._cycle = at
                if reason in FINAL_REASONS:
                    self.stop_reason = cast(FinalReason, reason)
                return reason
            else:
                raise RuntimeError(f"Unexpected avrsim reply: {kind} {at} {rest}")

    def _run_to(self, cycle: int) -> bool:
        """Run until a cycle and return whether the program is still running."""
        self._run(cycle)
        return self.running

    def _mark(self) -> None:
        """Start a new input: what the program did before it is not a reaction to it.

        A Serial line in progress is kept whole, so the line cursor moves to
        just after the last complete line.
        """
        self._since = len(self._records)
        for index in range(self._since - 1, self._line_start - 1, -1):
            record = self._records[index]
            if record.kind == "S" and record.value == NEWLINE:
                self._line_start = index + 1
                break

    def _wait(
        self, kind: RecordKind, key: int, matches: Callable[[Record], bool], *, timeout_ms: float
    ) -> Record | None:
        """Return the first unreturned record of a kind and key that matches.

        Records from before the latest input, and the initial states at cycle
        0, never match. When no recorded one matches, the program runs on
        until one is produced or the timeout passes.
        """
        deadline = self._cycle + to_cycles(timeout_ms)
        while True:
            start = max(self._since, self._consumed.get((kind, key), 0))
            for index in range(start, len(self._records)):
                record = self._records[index]
                if record.cycle and (record.kind, record.key) == (kind, key) and matches(record):
                    self._consumed[(kind, key)] = index + 1
                    return record
            # Records that did not match stay unreturned: a later wait for
            # another state may return them.
            if self._run(deadline, watch=(kind, key)) != "watched":
                return None

    # -- Driving the program ----------------------------------------------------

    @property
    def now_ms(self) -> float:
        """Simulated time since reset."""
        return to_ms(self._cycle)

    @property
    def running(self) -> bool:
        """Whether the program can still run."""
        return self.stop_reason is None

    def state(self, pin: PinLike) -> PinState:
        """Return the state the program has set a pin to, as of now."""
        return self._latest[pin_number(pin)]

    def run_until(self, ms: float) -> bool:
        """Run until ``ms`` from reset.

        Returns:
            Whether the program is still running.
        """
        return self._run_to(to_cycles(ms))

    def run_for(self, ms: float) -> bool:
        """Run for ``ms`` from now.

        Returns:
            Whether the program is still running.
        """
        return self._run_to(self._cycle + to_cycles(ms))

    def set(self, pin: PinLike, level: int | bool) -> None:
        """Drive a digital input from outside, overriding any internal pull-up."""
        self._mark()
        self._command(f"set {pin_number(pin)} {1 if level else 0}")

    def release(self, pin: PinLike) -> None:
        """Stop driving a digital input from outside.

        The pin then reads HIGH under the program's ``INPUT_PULLUP`` and LOW
        otherwise, as an unconnected pin does.
        """
        self._command(f"release {pin_number(pin)}")

    def analog(self, pin: PinLike, value: int) -> None:
        """Make ``analogRead()`` on A0-A5 return ``value`` (0-1023) from now on.

        Raises:
            ValueError: If the pin is not an analog input or the value is out of range.
        """
        channel = pin_number(pin) - ANALOG_PINS["A0"]
        if channel < 0 or not 0 <= value <= 1023:
            raise ValueError(f"Invalid analog input {pin!r} = {value!r}")
        self._mark()
        self._command(f"analog {channel} {int(value)}")

    def send(self, text: str | bytes) -> None:
        """Send text or bytes to the program's Serial, one byte per millisecond."""
        data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
        self._mark()
        for start in range(0, len(data), SEND_CHUNK):
            self._command("send " + data[start : start + SEND_CHUNK].hex())

    def pulse(self, pin: PinLike, level: int | bool, *, duration_ms: float) -> bool:
        """Drive a pin to ``level`` now and release it ``duration_ms`` later.

        A button press is a HIGH pulse, or a LOW one for a button to ground:
        released, the pin reads the program's pull-up again, or stays LOW if
        the program did not enable one. Time advances by ``duration_ms``.

        Args:
            pin: The input pin.
            level: The level during the pulse.
            duration_ms: How long the pulse lasts.

        Returns:
            Whether the program is still running.
        """
        self.set(pin, level)
        running = self.run_for(duration_ms)
        self.release(pin)
        return running

    def wait_for(self, pin: PinLike, state: StateLike = None, *, timeout_ms: float) -> float | None:
        """Return when the program next changed a pin, running on until it does.

        Changes are handed out in order: the first change of the pin (to
        ``state``, if given) not returned before, since the latest input, is
        returned at once, even though it happened before now. Only when there
        is none does the program run on, for ``timeout_ms`` at most.

        Args:
            pin: The pin to watch.
            state: Only count a change to this state, if given.
            timeout_ms: How long to run for the change at most.

        Returns:
            The time of the change in ms, or ``None`` on timeout or if the
            program stopped first.
        """
        wanted = _as_state(state)
        record = self._wait(
            "P",
            pin_number(pin),
            lambda record: wanted is None or record.value is wanted,
            timeout_ms=timeout_ms,
        )
        return None if record is None else to_ms(record.cycle)

    def wait_for_line(self, *, timeout_ms: float) -> Line | None:
        """Return the next Serial line the program completed, running on until it does.

        Lines are handed out in order: the first line not returned before,
        since the latest input, is returned at once; only when there is none
        does the program run on, for ``timeout_ms`` at most.

        Returns:
            The line, or ``None`` on timeout or if the program stopped first.
        """
        deadline = self._cycle + to_cycles(timeout_ms)
        while True:
            line = self._next_line()
            if line is not None or self._run(deadline, watch=("S", 0)) != "watched":
                return line

    def _next_line(self) -> Line | None:
        """Return the first complete Serial line no wait has returned, advancing past it."""
        data = bytearray()
        for index in range(self._line_start, len(self._records)):
            record = self._records[index]
            if record.kind != "S" or not isinstance(record.value, int):
                continue
            if record.value == NEWLINE:
                self._line_start = index + 1
                return Line(to_ms(record.cycle), data.decode("utf-8", "replace").rstrip("\r"))
            data.append(record.value)
        return None

    @property
    def trace(self) -> Trace:
        """Everything recorded so far, as a trace ending now."""
        return Trace(
            self._records,
            end_cycle=self._cycle,
            stop_reason=self.stop_reason or "end",
            max_pin_changes=self.max_pin_changes,
            max_serial_bytes=self.max_serial_bytes,
        )
