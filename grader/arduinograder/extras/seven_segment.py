"""Lit segments of a seven-segment display, from recorded pin states."""

import enum

from ..simulation import pin_number


class Segment(enum.Flag):
    """A set of segments: A-G and the decimal point DP.

    Bit n is segment n in Velxio's A-G, DP order, so Segment(0x3F) is a 0.
    """

    A = 0x01
    B = 0x02
    C = 0x04
    D = 0x08
    E = 0x10
    F = 0x20
    G = 0x40
    DP = 0x80

    def __str__(self):
        return ", ".join(segment.name for segment in self) or "none"


class SevenSegment:
    """One digit with segments A-G and DP on the given pins, in that order.

    Give None for a segment that is not wired. Which segments count as which
    digit is up to each question.
    """

    def __init__(self, pins, *, common="cathode"):
        if len(pins) != len(Segment) or common not in ("cathode", "anode"):
            raise ValueError(
                "Give eight pins in the order A-G, DP (None if unwired) and a "
                "common cathode or anode."
            )
        self.pins = [None if pin is None else pin_number(pin) for pin in pins]
        self.lit_level = 1 if common == "cathode" else 0

    def segments(self, trace, at_ms):
        """The lit Segment set. Unwired segments and input pins are off."""
        lit = Segment(0)
        for segment, pin in zip(Segment, self.pins):
            if pin is not None and trace.level(pin, at_ms) == self.lit_level:
                lit |= segment
        return lit
