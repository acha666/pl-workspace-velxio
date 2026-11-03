"""Inputs applied at fixed times, for running a program open loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias

from ..board import ANALOG_PINS, Level, PinLike, pin_number, to_cycles


class Inputs(Protocol):
    """What an event applies itself to: a program's inputs, as ``Session`` offers them."""

    def set(self, pin: PinLike, level: int | bool) -> None:
        """Drive a digital input from outside."""
        ...

    def release(self, pin: PinLike) -> None:
        """Stop driving a digital input from outside."""
        ...

    def analog(self, pin: PinLike, value: int) -> None:
        """Set what ``analogRead()`` returns on a pin."""
        ...

    def send(self, text: str | bytes) -> None:
        """Send bytes to the program's Serial."""
        ...


class Event(Protocol):
    """An input a scenario applies at a time.

    Events are frozen dataclasses, so a scenario's events can be hashed into
    its ``key``; a new kind of input is a new event class with ``apply()``.
    """

    @property
    def cycle(self) -> int:
        """When, in CPU cycles from reset."""
        ...

    @property
    def order(self) -> int:
        """The position among the scenario's events, to keep ties stable."""
        ...

    def apply(self, inputs: Inputs) -> None:
        """Apply the input now."""
        ...


ScenarioKey: TypeAlias = tuple[float, int, int, tuple[Event, ...]]
"""What makes two scenarios the same run: duration, limits and events; hashable."""


@dataclass(frozen=True)
class DigitalEvent:
    """Drive a digital pin from outside.

    Attributes:
        cycle: When, in CPU cycles from reset.
        order: The position among the scenario's events, to keep ties stable.
        pin: The Uno pin number.
        level: The level to drive.
    """

    cycle: int
    order: int
    pin: int
    level: Level

    def apply(self, inputs: Inputs) -> None:
        """Drive the pin."""
        inputs.set(self.pin, self.level)


@dataclass(frozen=True)
class ReleaseEvent:
    """Stop driving a digital pin from outside.

    Attributes:
        cycle: When, in CPU cycles from reset.
        order: The position among the scenario's events, to keep ties stable.
        pin: The Uno pin number.
    """

    cycle: int
    order: int
    pin: int

    def apply(self, inputs: Inputs) -> None:
        """Release the pin."""
        inputs.release(self.pin)


@dataclass(frozen=True)
class AnalogEvent:
    """Set what ``analogRead()`` returns on a channel.

    Attributes:
        cycle: When, in CPU cycles from reset.
        order: The position among the scenario's events, to keep ties stable.
        channel: The ADC channel, 0-5 for A0-A5.
        value: The reading, 0-1023.
    """

    cycle: int
    order: int
    channel: int
    value: int

    def apply(self, inputs: Inputs) -> None:
        """Set the reading."""
        inputs.analog(ANALOG_PINS["A0"] + self.channel, self.value)


@dataclass(frozen=True)
class SendEvent:
    """Send bytes to the program's Serial.

    Attributes:
        cycle: When the first byte is queued, in CPU cycles from reset.
        order: The position among the scenario's events, to keep ties stable.
        data: The bytes, delivered one per millisecond.
    """

    cycle: int
    order: int
    data: bytes

    def apply(self, inputs: Inputs) -> None:
        """Queue the bytes."""
        inputs.send(self.data)


class Scenario:
    """Inputs applied at set times, from reset until ``duration_ms``.

    Pins that are never set, or released, float LOW, or read HIGH under
    ``INPUT_PULLUP``. Serial input arrives at one byte per millisecond. Every
    method that adds an input returns the scenario, for chaining.

    Attributes:
        duration_ms: How long to run from reset.
        max_pin_changes: Stop early once the program has changed its pins this
            many times, for runaway programs.
        max_serial_bytes: Stop early once the program has sent this many bytes.
    """

    def __init__(
        self,
        duration_ms: float,
        *,
        max_pin_changes: int = 200_000,
        max_serial_bytes: int = 65_536,
    ) -> None:
        """Start an empty scenario.

        Raises:
            ValueError: If ``duration_ms`` is not positive.
        """
        if duration_ms <= 0:
            raise ValueError("A scenario needs a positive duration.")
        self.duration_ms = duration_ms
        self.max_pin_changes = max_pin_changes
        self.max_serial_bytes = max_serial_bytes
        self._events: list[Event] = []

    def _at(self, at_ms: float) -> tuple[int, int]:
        if at_ms > self.duration_ms:
            raise ValueError(f"Event at {at_ms} ms is after the scenario ends.")
        return to_cycles(at_ms), len(self._events)

    def set(self, pin: PinLike, level: int | bool, *, at_ms: float = 0) -> Scenario:
        """Drive a digital input from outside, overriding any internal pull-up.

        Args:
            pin: The input pin.
            level: HIGH (1) or LOW (0).
            at_ms: When to apply it.

        Raises:
            ValueError: If the pin is invalid or the time is after the end.
        """
        cycle, order = self._at(at_ms)
        value: Level = 1 if level else 0
        self._events.append(DigitalEvent(cycle, order, pin_number(pin), value))
        return self

    def release(self, pin: PinLike, *, at_ms: float = 0) -> Scenario:
        """Stop driving a digital input from outside at ``at_ms``.

        The pin then reads HIGH under the program's ``INPUT_PULLUP`` and LOW
        otherwise, as an unconnected pin does.

        Raises:
            ValueError: If the pin is invalid or the time is after the end.
        """
        cycle, order = self._at(at_ms)
        self._events.append(ReleaseEvent(cycle, order, pin_number(pin)))
        return self

    def pulse(
        self, pin: PinLike, level: int | bool, *, at_ms: float, duration_ms: float
    ) -> Scenario:
        """Drive a pin to ``level`` at ``at_ms`` and release it ``duration_ms`` later.

        A button press is a HIGH pulse, or a LOW one for a button to ground:
        released, the pin reads the program's pull-up again, or stays LOW if
        the program did not enable one.

        Args:
            pin: The input pin.
            level: The level during the pulse.
            at_ms: When the pulse starts.
            duration_ms: How long it lasts.
        """
        self.set(pin, level, at_ms=at_ms)
        return self.release(pin, at_ms=at_ms + duration_ms)

    def analog(self, pin: PinLike, value: int, *, at_ms: float = 0) -> Scenario:
        """Make ``analogRead()`` on A0-A5 return ``value`` (0-1023) from ``at_ms`` on.

        Raises:
            ValueError: If the pin is not an analog input or the value is out of range.
        """
        channel = pin_number(pin) - ANALOG_PINS["A0"]
        if channel < 0 or not 0 <= value <= 1023:
            raise ValueError(f"Invalid analog input {pin!r} = {value!r}")
        cycle, order = self._at(at_ms)
        self._events.append(AnalogEvent(cycle, order, channel, int(value)))
        return self

    def send(self, text: str | bytes, *, at_ms: float = 0) -> Scenario:
        """Send text or bytes to the program's Serial, starting at ``at_ms``."""
        data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
        cycle, order = self._at(at_ms)
        self._events.append(SendEvent(cycle, order, data))
        return self

    @property
    def events(self) -> list[Event]:
        """The events in time order; events at the same time keep their order."""
        return sorted(self._events, key=lambda event: (event.cycle, event.order))

    @property
    def key(self) -> ScenarioKey:
        """A hashable identity, so the trace of a scenario can be cached."""
        return (self.duration_ms, self.max_pin_changes, self.max_serial_bytes, tuple(self.events))

    def __repr__(self) -> str:
        return f"Scenario(duration_ms={self.duration_ms}, events={len(self._events)})"
