"""Arduino Uno pins and simulated time.

Tests name pins by Uno number (0-19) or analog name (``"A0"`` to ``"A5"``)
and give times in milliseconds from reset. The simulator counts CPU cycles at
16 MHz, and this module converts between the two.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal, TypeAlias

F_CPU: Final = 16_000_000
"""The Uno's clock frequency in Hz."""
CYCLES_PER_MS: Final = F_CPU // 1000
"""CPU cycles in one millisecond of simulated time."""
HIGH: Final[Literal[1]] = 1
"""The HIGH level, as in Arduino's ``HIGH``."""
LOW: Final[Literal[0]] = 0
"""The LOW level, as in Arduino's ``LOW``."""
NUM_PINS: Final = 20
"""How many pins the Uno has: digital 0-13 and analog A0-A5 as 14-19."""
ANALOG_PINS: Final[Mapping[str, int]] = {f"A{channel}": 14 + channel for channel in range(6)}
"""Uno pin numbers of the analog inputs ``"A0"`` to ``"A5"``."""

PinLike: TypeAlias = int | str
"""A pin given as an Uno number or as a name such as ``"13"`` or ``"A0"``."""
Level: TypeAlias = Literal[0, 1]
"""An output level: 1 for HIGH, 0 for LOW."""


def pin_number(pin: PinLike) -> int:
    """Return the Uno pin number for a pin given in any accepted form.

    Args:
        pin: An Uno pin number 0-19, or its name such as ``"13"`` or ``"A0"``.

    Returns:
        The pin number, 0-19.

    Raises:
        ValueError: If ``pin`` is not an Uno pin.
    """
    if isinstance(pin, str):
        name = pin.strip().upper()
        if name in ANALOG_PINS:
            return ANALOG_PINS[name]
        if name.isdigit() and int(name) < NUM_PINS:
            return int(name)
    if isinstance(pin, int) and not isinstance(pin, bool) and 0 <= pin < NUM_PINS:
        return pin
    raise ValueError(f"Not an Arduino Uno pin: {pin!r}")


def pin_name(number: int) -> str:
    """Return ``"13"`` or ``"A0"`` for a pin number."""
    return next((name for name, n in ANALOG_PINS.items() if n == number), str(number))


def to_cycles(ms: float) -> int:
    """Return the CPU cycle count for a time in milliseconds from reset.

    Raises:
        ValueError: If ``ms`` is negative.
    """
    if ms < 0:
        raise ValueError(f"Times must not be negative: {ms!r}")
    return round(ms * CYCLES_PER_MS)


def to_ms(cycle: int) -> float:
    """Return the time in milliseconds from reset for a CPU cycle count."""
    return cycle / CYCLES_PER_MS
