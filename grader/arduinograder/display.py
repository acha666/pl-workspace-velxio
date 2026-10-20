"""Seven-segment display decoding from recorded pin states."""

from .simulation import pin_number

# Segments lit for each character, using the standard a-g lettering.
DIGITS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abdeg",
    "3": "abcdg",
    "4": "bcfg",
    "5": "acdfg",
    "6": "acdefg",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
    " ": "",
}


class SevenSegment:
    """A display with segments a-g on the given pins.

    font maps each character to its segments, as a string or a list of
    accepted alternatives (for example "7": ["abc", "abcf"]).
    """

    def __init__(self, pins, *, common="cathode", font=DIGITS):
        if len(pins) != 7 or common not in ("cathode", "anode"):
            raise ValueError("Give seven pins (a-g) and a common cathode or anode.")
        self.pins = [pin_number(pin) for pin in pins]
        self.lit_level = 1 if common == "cathode" else 0
        self._characters = {}
        for character, patterns in font.items():
            for pattern in [patterns] if isinstance(patterns, str) else patterns:
                self._characters["".join(sorted(pattern))] = character

    def segments(self, trace, at_ms):
        """Lit segments as letters, e.g. "bc". Pins left as inputs are off."""
        levels = trace.levels(self.pins, at_ms)
        return "".join(
            segment
            for segment, level in zip("abcdefg", levels)
            if level == self.lit_level
        )

    def read(self, trace, at_ms):
        """The character shown, or None if the lit segments match no character."""
        return self._characters.get(self.segments(trace, at_ms))
