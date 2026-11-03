"""Optional helpers for questions with particular needs.

Each encodes a grading policy or assumes a circuit; the core package can
express the same checks with ``Trace``.
"""

from .calls import Call, find_calls, forbid_calls, no_calls
from .seven_segment import Segment, SevenSegment

__all__ = ["Call", "Segment", "SevenSegment", "find_calls", "forbid_calls", "no_calls"]
