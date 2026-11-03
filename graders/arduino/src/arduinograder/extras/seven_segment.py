"""Lit segments of a seven-segment display, from recorded pin states."""

from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import Literal

from ..board import Level, PinLike, pin_number
from ..sim.trace import Trace


class Segment(enum.Flag):
    """A set of segments: A-G and the decimal point DP.

    Bit n is segment n in Velxio's A-G, DP order, so ``Segment(0x3F)`` is a 0.
    """

    A = 0x01
    B = 0x02
    C = 0x04
    D = 0x08
    E = 0x10
    F = 0x20
    G = 0x40
    DP = 0x80

    def __str__(self) -> str:
        return (
            ", ".join(name for name, segment in Segment.__members__.items() if segment in self)
            or "none"
        )


class SevenSegment:
    """One digit with segments A-G and DP on the given pins, in that order.

    Which segments count as which digit is up to each question.

    Attributes:
        pins: The Uno pin of each segment in A-G, DP order, ``None`` if unwired.
        lit_level: The output level that lights a segment.
    """

    def __init__(
        self, pins: Sequence[PinLike | None], *, common: Literal["cathode", "anode"] = "cathode"
    ) -> None:
        """Describe how the display is wired.

        Args:
            pins: Eight pins in the order A-G, DP, with ``None`` for a segment
                that is not wired.
            common: ``"cathode"`` lights a segment when its pin is HIGH,
                ``"anode"`` when LOW.

        Raises:
            ValueError: If there are not eight pins or ``common`` is unknown.
        """
        if len(pins) != len(Segment) or common not in ("cathode", "anode"):
            raise ValueError(
                "Give eight pins in the order A-G, DP (None if unwired) and a "
                "common cathode or anode."
            )
        self.pins: list[int | None] = [None if pin is None else pin_number(pin) for pin in pins]
        self.lit_level: Level = 1 if common == "cathode" else 0

    def segments(self, trace: Trace, at_ms: float) -> Segment:
        """Return the lit segments at a time. Unwired segments and input pins are off."""
        lit = Segment(0)
        for segment, pin in zip(Segment.__members__.values(), self.pins, strict=True):
            if pin is not None and trace.pin(pin).level(at_ms) == self.lit_level:
                lit |= segment
        return lit
