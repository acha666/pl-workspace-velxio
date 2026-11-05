"""Optional helpers for particular question designs.

Each encodes a grading policy or assumes a circuit that the core API could
express as well, so import one only when the question needs it.
"""

from .calls import Call, find_calls, forbid_calls, no_calls
from .seven_segment import Segment, SevenSegment

__all__ = ["Call", "Segment", "SevenSegment", "find_calls", "forbid_calls", "no_calls"]
