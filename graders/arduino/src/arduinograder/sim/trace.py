"""What a simulated program did: pin states and Serial output over time."""

from __future__ import annotations

import bisect
import enum
import itertools
from collections.abc import Iterable, Mapping
from typing import Final, Literal, NamedTuple, TypeAlias, assert_never, cast, get_args

from ..board import NUM_PINS, Level, PinLike, pin_name, pin_number, to_cycles, to_ms

StopReason: TypeAlias = Literal["end", "done", "crashed", "pin-limit", "serial-limit"]
"""Why a trace ends: ``"end"`` for a scenario run to completion, else early."""
STOP_REASONS: Final[frozenset[str]] = frozenset(get_args(StopReason))
MAX_DESCRIBED: Final = 25
"""Edge times ``Edges.describe()`` lists at most."""
RecordKind: TypeAlias = Literal["P", "S"]
"""The kinds of record avrsim reports: ``"P"`` for a pin state, ``"S"`` for a Serial byte."""


class PinState(enum.Enum):
    """A pin as set by the program: an output level or an input mode."""

    HIGH = "HIGH"
    LOW = "LOW"
    INPUT = "INPUT"
    INPUT_PULLUP = "INPUT_PULLUP"

    @property
    def is_output(self) -> bool:
        """Whether the program drives the pin."""
        return self in (PinState.HIGH, PinState.LOW)

    @property
    def is_input(self) -> bool:
        """Whether the pin is an input, with or without its pull-up."""
        return not self.is_output

    @property
    def is_high(self) -> bool:
        """Whether the pin is a HIGH output. An input with its pull-up is not driven."""
        return self is PinState.HIGH

    @property
    def is_low(self) -> bool:
        """Whether the pin is a LOW output."""
        return self is PinState.LOW

    @property
    def level(self) -> Level | None:
        """1 or 0 for an output, ``None`` for an input."""
        if self is PinState.HIGH:
            return 1
        if self is PinState.LOW:
            return 0
        return None

    def __str__(self) -> str:
        return self.value


STATE_CODES: Final[Mapping[str, PinState]] = {
    "H": PinState.HIGH,
    "L": PinState.LOW,
    "I": PinState.INPUT,
    "U": PinState.INPUT_PULLUP,
}
"""The one-letter state codes in avrsim's ``P`` records."""


LevelLike: TypeAlias = PinState | str | int
"""A level as ``HIGH``/``LOW`` (1/0), a bool, ``"HIGH"``/``"LOW"``, or an output ``PinState``."""


def as_level(value: LevelLike) -> Level:
    """Return 1 or 0 for a level given in any accepted form.

    Raises:
        ValueError: If ``value`` is not a level: an input ``PinState``, another
            string, or a number other than 0 and 1.
    """
    if isinstance(value, PinState):
        if value.level is None:
            raise ValueError(f"Not an output level: {value!r}")
        return value.level
    if isinstance(value, str):
        name = value.strip().upper()
        if name in ("HIGH", "1"):
            return 1
        if name in ("LOW", "0"):
            return 0
        raise ValueError(f"Not a level: {value!r}")
    if value in (0, 1):
        return 1 if value else 0
    raise ValueError(f"Not a level: {value!r}")


class Change(NamedTuple):
    """A recorded change of a pin's state.

    Attributes:
        time_ms: When the program changed the pin.
        state: The new state.
    """

    time_ms: float
    state: PinState


class Edge(NamedTuple):
    """A flip of a pin's output level.

    Attributes:
        time_ms: When the level flipped.
        level: The level after the edge: 1 for a rising edge, 0 for a falling one.
    """

    time_ms: float
    level: Level


class Line(NamedTuple):
    """A line the program sent on Serial.

    Attributes:
        time_ms: When its newline was transmitted, or its last byte if it has none.
        text: The line without its line ending.
    """

    time_ms: float
    text: str


class Record(NamedTuple):
    """One thing the program did, as avrsim reports it.

    Attributes:
        cycle: When, in CPU cycles from reset.
        kind: ``"P"`` for a pin state, ``"S"`` for a Serial byte.
        key: What it concerns: the pin number, or 0 for Serial.
        value: The new ``PinState`` of a pin, or the byte sent on Serial.
    """

    cycle: int
    kind: RecordKind
    key: int
    value: PinState | int


class SimulationStopped(Exception):
    """A check asked about a time after the simulation ended early.

    The message explains to the student why it ended.
    """


class Edges(list[Edge]):
    """The output level changes of one pin in time order."""

    @property
    def times_ms(self) -> list[float]:
        """The time of each edge."""
        return [edge.time_ms for edge in self]

    def rising(self) -> Edges:
        """Return the edges to HIGH."""
        return Edges(edge for edge in self if edge.level == 1)

    def falling(self) -> Edges:
        """Return the edges to LOW."""
        return Edges(edge for edge in self if edge.level == 0)

    def intervals_ms(self) -> list[float]:
        """Return the time from each edge to the next."""
        return [after.time_ms - before.time_ms for before, after in itertools.pairwise(self)]

    def match(self, times_ms: Iterable[float], *, tolerance_ms: float) -> bool:
        """Return whether these are exactly the given times, each within ``tolerance_ms``."""
        times = list(times_ms)
        return len(self) == len(times) and all(
            abs(edge.time_ms - time) <= tolerance_ms for edge, time in zip(self, times, strict=True)
        )

    def periodic(self, period_ms: float, *, tolerance_ms: float) -> bool:
        """Return whether there are at least two edges, each ``period_ms`` after the last."""
        return len(self) >= 2 and all(
            abs(gap - period_ms) <= tolerance_ms for gap in self.intervals_ms()
        )

    def describe(self) -> str:
        """Return the edge times for a message: ``"500 ms, 1000 ms"``, or ``"never"``.

        Only the first ``MAX_DESCRIBED`` times are listed, then how many follow, as a
        pin flipping without end would make an endless message.
        """
        times = [f"{edge.time_ms:.0f} ms" for edge in self[:MAX_DESCRIBED]]
        if len(self) > MAX_DESCRIBED:
            times.append(f"and {len(self) - MAX_DESCRIBED} more")
        return ", ".join(times) or "never"


class PinTrace:
    """One pin's recorded states, queried in milliseconds from reset.

    Attributes:
        pin: The Uno pin number.
    """

    def __init__(self, trace: Trace, pin: int) -> None:
        """Bind to a pin's records in a trace; use ``Trace.pin()`` instead."""
        self._trace = trace
        self.pin = pin
        self._times = trace._times[pin]
        self._states = trace._states[pin]

    def __repr__(self) -> str:
        return f"<PinTrace {pin_name(self.pin)}>"

    def at(self, ms: float) -> PinState:
        """Return the pin's state at a time.

        Raises:
            SimulationStopped: If the program had stopped before ``ms``.
            ValueError: If ``ms`` is after the end of the simulation.
        """
        index = bisect.bisect_right(self._times, self._trace._cycle_at(ms)) - 1
        return self._states[index]

    def level(self, ms: float) -> Level | None:
        """Return 1 or 0 for an output at a time, ``None`` for an input."""
        return self.at(ms).level

    def _window(self, start_ms: float, end_ms: float | None) -> tuple[int, int]:
        """Return the window in cycles; both ends are checked as ``at()`` checks its time."""
        start = self._trace._cycle_at(start_ms)
        end = self._trace._end_cycle if end_ms is None else self._trace._cycle_at(end_ms)
        return start, end

    def changes(self, start_ms: float = 0, end_ms: float | None = None) -> list[Change]:
        """Return every change in ``[start_ms, end_ms]``, including input modes."""
        start, end = self._window(start_ms, end_ms)
        return [
            Change(to_ms(cycle), state)
            for cycle, state in zip(self._times, self._states, strict=True)
            if start <= cycle <= end
        ]

    def edges(self, start_ms: float = 0, end_ms: float | None = None) -> Edges:
        """Return the edges in ``[start_ms, end_ms]`` where the output level flipped.

        A change between input and output is not an edge: a pin driven HIGH, released,
        then driven LOW has one falling edge, at the LOW time.
        """
        start, end = self._window(start_ms, end_ms)
        edges, level = Edges(), None
        for cycle, state in zip(self._times, self._states, strict=True):
            if cycle > end:
                break
            if state.level is None:
                continue
            if cycle >= start and level is not None and state.level != level:
                edges.append(Edge(to_ms(cycle), state.level))
            level = state.level
        return edges

    def high_fraction(self, start_ms: float, end_ms: float) -> float:
        """Return the fraction of ``[start_ms, end_ms]`` the pin was a HIGH output.

        Raises:
            ValueError: If ``end_ms`` is not after ``start_ms``.
        """
        start, end = self._window(start_ms, end_ms)
        if end <= start:
            raise ValueError("high_fraction needs end_ms after start_ms.")
        high, since, state = 0, start, self.at(start_ms)
        for cycle, next_state in zip(self._times, self._states, strict=True):
            if cycle <= start:
                continue
            if cycle > end:
                break
            if state.is_high:
                high += cycle - since
            since, state = cycle, next_state
        if state.is_high:
            high += end - since
        return high / (end - start)

    def stable(self, start_ms: float, end_ms: float) -> bool:
        """Return whether the pin did not change after ``start_ms`` up to ``end_ms``."""
        start, end = self._window(start_ms, end_ms)
        return not any(start < cycle <= end for cycle in self._times)


class SerialTrace:
    """Bytes the program transmitted on Serial, each at the time it was sent."""

    def __init__(self, trace: Trace, data: list[tuple[int, int]]) -> None:
        """Bind to a trace's serial records; use ``Trace.serial`` instead."""
        self._trace = trace
        self._data = data

    def __len__(self) -> int:
        return len(self._data)

    def __bool__(self) -> bool:
        return bool(self._data)

    def _window(self, start_ms: float, end_ms: float | None) -> list[tuple[int, int]]:
        """Return the bytes in the window; both ends are checked as ``PinTrace.at()`` checks."""
        start = self._trace._cycle_at(start_ms)
        end = self._trace._end_cycle if end_ms is None else self._trace._cycle_at(end_ms)
        return [(cycle, byte) for cycle, byte in self._data if start <= cycle <= end]

    def bytes(self, start_ms: float = 0, end_ms: float | None = None) -> bytes:
        """Return the bytes sent in ``[start_ms, end_ms]``."""
        return bytes(byte for _, byte in self._window(start_ms, end_ms))

    def text(self, start_ms: float = 0, end_ms: float | None = None) -> str:
        """Return the bytes sent in ``[start_ms, end_ms]`` decoded as UTF-8."""
        return self.bytes(start_ms, end_ms).decode("utf-8", "replace")

    def lines(self, start_ms: float = 0, end_ms: float | None = None) -> list[Line]:
        """Return the lines sent in ``[start_ms, end_ms]``, each timed by its newline.

        A final line without a newline is included at its last byte's time.
        """
        lines: list[Line] = []
        current, last = bytearray(), 0
        for cycle, byte in self._window(start_ms, end_ms):
            last = cycle
            if byte == ord("\n"):
                lines.append(Line(to_ms(cycle), _decode_line(current)))
                current = bytearray()
            else:
                current.append(byte)
        if current:
            lines.append(Line(to_ms(last), _decode_line(current)))
        return lines


def _decode_line(data: bytearray) -> str:
    return data.decode("utf-8", "replace").rstrip("\r")


class Trace:
    """Pin states and Serial output recorded while a program ran.

    Attributes:
        stop_reason: ``"end"`` when the program ran to the end of its scenario or
            session, else why the simulation ended early; asking about a later
            time then raises ``SimulationStopped``.
        max_pin_changes: The pin change limit in force, for messages.
        max_serial_bytes: The Serial byte limit in force, for messages.
    """

    def __init__(
        self,
        records: Iterable[Record],
        *,
        end_cycle: int,
        stop_reason: StopReason,
        max_pin_changes: int | None = None,
        max_serial_bytes: int | None = None,
    ) -> None:
        """Build a trace from what was recorded.

        Args:
            records: The ``Record`` list in time order. Pins without a record
                at cycle 0 start as ``INPUT``.
            end_cycle: The cycle the trace ends at.
            stop_reason: Why it ends.
            max_pin_changes: The pin change limit in force.
            max_serial_bytes: The Serial byte limit in force.

        Raises:
            ValueError: If a record's kind and value do not go together.
        """
        self._times: dict[int, list[int]] = {pin: [] for pin in range(NUM_PINS)}
        self._states: dict[int, list[PinState]] = {pin: [] for pin in range(NUM_PINS)}
        self._serial: list[tuple[int, int]] = []
        for record in records:
            if record.kind == "P" and isinstance(record.value, PinState):
                self._times[record.key].append(record.cycle)
                self._states[record.key].append(record.value)
            elif record.kind == "S" and isinstance(record.value, int):
                self._serial.append((record.cycle, record.value))
            else:
                raise ValueError(f"Malformed trace record: {record!r}")
        for pin in range(NUM_PINS):
            if not self._times[pin] or self._times[pin][0] != 0:
                self._times[pin].insert(0, 0)
                self._states[pin].insert(0, PinState.INPUT)
        self._end_cycle = end_cycle
        self.stop_reason = stop_reason
        self.max_pin_changes = max_pin_changes
        self.max_serial_bytes = max_serial_bytes

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        max_pin_changes: int | None = None,
        max_serial_bytes: int | None = None,
    ) -> Trace:
        """Build a trace from avrsim reply lines, mainly for tests.

        Args:
            text: ``P``, ``S`` and ``T`` records, one per line; the last ``T``
                ends the trace, and ``reached`` counts as ``"end"``.
            max_pin_changes: The pin change limit in force.
            max_serial_bytes: The Serial byte limit in force.

        Raises:
            ValueError: If a record is malformed or there is no ``T`` record.
        """
        records: list[Record] = []
        end, reason = 0, None
        for line in text.splitlines():
            if not line.strip():
                continue
            kind, cycle_text, *rest = line.split()
            cycle = int(cycle_text)
            if kind == "P" and rest[1] in STATE_CODES:
                records.append(Record(cycle, "P", int(rest[0]), STATE_CODES[rest[1]]))
            elif kind == "S":
                records.append(Record(cycle, "S", 0, int(rest[0])))
            elif kind == "T":
                end, reason = cycle, rest[0]
            else:
                raise ValueError(f"Unknown trace record: {line!r}")
        if reason is None:
            raise ValueError("The trace has no end record.")
        return cls(
            records,
            end_cycle=end,
            stop_reason=as_stop_reason(reason),
            max_pin_changes=max_pin_changes,
            max_serial_bytes=max_serial_bytes,
        )

    def __repr__(self) -> str:
        return f"<Trace to {self.end_ms:.0f} ms, {self.stop_reason}>"

    @property
    def end_ms(self) -> float:
        """When the trace ends."""
        return to_ms(self._end_cycle)

    @property
    def ended_early(self) -> bool:
        """Whether the simulation ended before its scenario or session did."""
        return self.stop_reason != "end"

    @property
    def stop_message(self) -> str | None:
        """A student-facing explanation when the simulation ended early, else ``None``."""
        at = f"{self.end_ms:.0f} ms"
        match self.stop_reason:
            case "end":
                return None
            case "done":
                return f"The program stopped running at {at}."
            case "crashed":
                return f"The program crashed at {at}, so the simulation stopped."
            case "pin-limit":
                return (
                    f"The simulation stopped at {at} because the program had changed its pins "
                    f"{self.max_pin_changes} times, the limit for this question."
                )
            case "serial-limit":
                return (
                    f"The simulation stopped at {at} because the program had printed "
                    f"{self.max_serial_bytes} bytes on Serial, the limit for this question."
                )
            case never:
                assert_never(never)

    def _cycle_at(self, ms: float) -> int:
        """Return the cycle for a time, checking it is within the trace."""
        cycle = to_cycles(ms)
        if cycle > self._end_cycle:
            if self.ended_early:
                raise SimulationStopped(self.stop_message)
            raise ValueError(f"{ms} ms is after the simulation ends at {self.end_ms} ms.")
        return cycle

    def pin(self, pin: PinLike) -> PinTrace:
        """Return the records of an Uno pin, 0-19 or ``"A0"`` to ``"A5"``."""
        return PinTrace(self, pin_number(pin))

    def levels(self, pins: Iterable[PinLike], at_ms: float) -> tuple[Level | None, ...]:
        """Return the output levels (1, 0 or ``None`` for an input) of several pins at once."""
        return tuple(self.pin(pin).level(at_ms) for pin in pins)

    @property
    def serial(self) -> SerialTrace:
        """What the program sent on Serial."""
        return SerialTrace(self, self._serial)


def as_stop_reason(text: str) -> StopReason:
    """Return the ``StopReason`` for an avrsim reason word.

    Raises:
        ValueError: If the word is not a reason a trace can end with.
    """
    if text == "reached":
        return "end"
    if text not in STOP_REASONS:
        raise ValueError(f"Unknown stop reason: {text!r}")
    return cast(StopReason, text)
