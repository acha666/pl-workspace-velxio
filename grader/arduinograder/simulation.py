"""Scripted inputs for avrsim and queries over the trace it records."""

import bisect

F_CPU = 16_000_000
CYCLES_PER_MS = F_CPU // 1000
HIGH = 1
LOW = 0
ANALOG_PINS = {f"A{channel}": 14 + channel for channel in range(6)}
STATES = {"H": "HIGH", "L": "LOW", "I": "INPUT", "U": "INPUT_PULLUP"}


def pin_number(pin):
    """Arduino Uno pin number for 0-19 or "A0"-"A5"."""
    if isinstance(pin, str) and pin.upper() in ANALOG_PINS:
        return ANALOG_PINS[pin.upper()]
    if isinstance(pin, int) and not isinstance(pin, bool) and 0 <= pin < 20:
        return pin
    raise ValueError(f"Not an Arduino Uno pin: {pin!r}")


def _cycle(ms):
    if ms < 0:
        raise ValueError(f"Times must not be negative: {ms!r}")
    return round(ms * CYCLES_PER_MS)


def _ms(cycle):
    return cycle / CYCLES_PER_MS


class Scenario:
    """Inputs applied at simulated times, from reset until duration_ms.

    Pins that are never set float LOW, or read HIGH under INPUT_PULLUP.
    """

    def __init__(
        self, duration_ms, *, max_pin_changes=200_000, max_serial_bytes=65_536
    ):
        if duration_ms <= 0:
            raise ValueError("A scenario needs a positive duration.")
        self.duration_ms = duration_ms
        self.max_pin_changes = max_pin_changes
        self.max_serial_bytes = max_serial_bytes
        self._events = []

    def _add(self, at_ms, kind, number, value):
        if at_ms > self.duration_ms:
            raise ValueError(f"Event at {at_ms} ms is after the scenario ends.")
        self._events.append((_cycle(at_ms), len(self._events), kind, number, value))
        return self

    def set(self, pin, level, *, at_ms=0):
        """Drive a digital input from outside, overriding any internal pull-up."""
        return self._add(at_ms, "digital", pin_number(pin), 1 if level else 0)

    def press(self, pin, *, at_ms, hold_ms, active=HIGH):
        """Press a button at at_ms and release it hold_ms later."""
        self.set(pin, active, at_ms=at_ms)
        return self.set(pin, not active, at_ms=at_ms + hold_ms)

    def analog(self, pin, value, *, at_ms=0):
        """Make analogRead() on A0-A5 return value (0-1023)."""
        channel = pin_number(pin) - ANALOG_PINS["A0"]
        if channel < 0 or not 0 <= value <= 1023:
            raise ValueError(f"Invalid analog input {pin!r} = {value!r}")
        return self._add(at_ms, "analog", channel, int(value))

    def to_text(self):
        lines = [
            f"duration {_cycle(self.duration_ms)}",
            f"limit pins {self.max_pin_changes}",
            f"limit serial {self.max_serial_bytes}",
        ]
        for cycle, _, kind, number, value in sorted(self._events):
            lines.append(f"{kind} {cycle} {number} {value}")
        return "\n".join(lines) + "\n"


class SimulationStopped(Exception):
    """A check asked about a time after the program stopped being simulated."""


class Trace:
    """Pin states and Serial output recorded by avrsim, queried in milliseconds."""

    def __init__(self, text, scenario):
        self._times = {pin: [] for pin in range(20)}
        self._states = {pin: [] for pin in range(20)}
        self._serial = []
        self.stop_reason = None
        self._end_cycle = 0
        self._scenario = scenario
        for line in text.splitlines():
            kind, cycle, *rest = line.split()
            cycle = int(cycle)
            if kind == "P":
                pin = int(rest[0])
                self._times[pin].append(cycle)
                self._states[pin].append(STATES[rest[1]])
            elif kind == "S":
                self._serial.append((cycle, int(rest[0])))
            elif kind == "E":
                self._end_cycle, self.stop_reason = cycle, rest[0]
        if self.stop_reason is None:
            raise ValueError("The trace has no end record.")

    @property
    def end_ms(self):
        return _ms(self._end_cycle)

    @property
    def stop_message(self):
        """Student-facing explanation when the simulation ended early, else None."""
        at = f"{self.end_ms:.0f} ms"
        return {
            "end": None,
            "done": f"The program stopped running at {at}.",
            "crashed": f"The program crashed at {at}, so the simulation stopped.",
            "pin-limit": (
                f"The simulation stopped at {at} because the program changed its pins "
                f"more than {self._scenario.max_pin_changes} times."
            ),
            "serial-limit": (
                f"The simulation stopped at {at} because the program printed more than "
                f"{self._scenario.max_serial_bytes} bytes on Serial."
            ),
        }.get(self.stop_reason, f"The simulation stopped at {at} ({self.stop_reason}).")

    def _cycle_at(self, at_ms):
        cycle = _cycle(at_ms)
        if cycle > self._end_cycle:
            if self.stop_reason != "end":
                raise SimulationStopped(self.stop_message)
            raise ValueError(f"{at_ms} ms is after the scenario ends.")
        return cycle

    def state(self, pin, at_ms):
        """ "HIGH", "LOW", "INPUT" or "INPUT_PULLUP" as set by the program."""
        pin = pin_number(pin)
        index = bisect.bisect_right(self._times[pin], self._cycle_at(at_ms)) - 1
        return self._states[pin][index]

    def level(self, pin, at_ms):
        """1 or 0 for an output pin, None for an input."""
        return {"HIGH": 1, "LOW": 0}.get(self.state(pin, at_ms))

    def levels(self, pins, at_ms):
        return tuple(self.level(pin, at_ms) for pin in pins)

    def changes(self, pin, start_ms=0, end_ms=None):
        """(time_ms, state) for each change in [start_ms, end_ms]."""
        pin = pin_number(pin)
        start = _cycle(start_ms)
        end = self._end_cycle if end_ms is None else self._cycle_at(end_ms)
        return [
            (_ms(cycle), state)
            for cycle, state in zip(self._times[pin], self._states[pin])
            if start <= cycle <= end
        ]

    def serial_text(self, start_ms=0, end_ms=None):
        start = _cycle(start_ms)
        end = self._end_cycle if end_ms is None else self._cycle_at(end_ms)
        data = bytes(byte for cycle, byte in self._serial if start <= cycle <= end)
        return data.decode("utf-8", "replace")

    def serial_lines(self):
        """(time_ms, text) for each Serial line, timed when its newline was sent.

        A final line without a newline is included at its last byte's time.
        """
        lines, current, last = [], bytearray(), None
        for cycle, byte in self._serial:
            last = cycle
            if byte == ord("\n"):
                lines.append(
                    (_ms(cycle), current.decode("utf-8", "replace").rstrip("\r"))
                )
                current = bytearray()
            else:
                current.append(byte)
        if current:
            lines.append((_ms(last), current.decode("utf-8", "replace").rstrip("\r")))
        return lines
