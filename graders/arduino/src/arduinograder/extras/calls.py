"""Static checks on sketch source using the tree-sitter C++ grammar."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Final, NamedTuple

import tree_sitter_cpp
from tree_sitter import Language, Parser

from ..errors import StopGrading


class Call(NamedTuple):
    """A call found in a sketch.

    Attributes:
        name: The called function's name.
        line: The 1-based line of the call.
        text: That line, stripped.
    """

    name: str
    line: int
    text: str


_PARSER: Final = Parser(Language(tree_sitter_cpp.language()))


def find_calls(source: str, names: Iterable[str]) -> list[Call]:
    """Return calls to the named functions, ignoring comments and string literals.

    Matches plain and ``::``-qualified calls such as ``delay(10)`` and
    ``::delay(10)``. Calls hidden behind macros or function pointers are not
    detected.

    Args:
        source: The sketch's text.
        names: The function names to look for.

    Returns:
        The calls in line order.
    """
    wanted = set(names)
    lines = source.split("\n")  # tree-sitter rows split on "\n" only
    calls: list[Call] = []
    stack = [_PARSER.parse(source.encode("utf-8")).root_node]
    while stack:
        node = stack.pop()
        if node.type == "call_expression":
            function = node.child_by_field_name("function")
            if function is not None and function.type == "qualified_identifier":
                function = function.child_by_field_name("name")
            if function is not None and function.type == "identifier" and function.text:
                name = function.text.decode("utf-8")
                if name in wanted:
                    row = node.start_point.row
                    text = lines[row].strip() if row < len(lines) else ""
                    calls.append(Call(name, row + 1, text))
        stack.extend(reversed(node.children))
    return sorted(calls, key=lambda call: call.line)


def forbid_calls(source: str, *names: str) -> None:
    """Stop grading with a score of zero if the source calls any of these functions.

    Raises:
        StopGrading: Listing up to three of the calls.
    """
    calls = find_calls(source, names)
    if calls:
        listed = "\n".join(f"    line {call.line}: {call.text}" for call in calls[:3])
        called = ", ".join(sorted({f"{call.name}()" for call in calls}))
        raise StopGrading(
            f"Your sketch calls {called}, which this question does not allow:\n{listed}"
        )


def no_calls(*names: str) -> Callable[[str], None]:
    """Return a gate that stops grading with score 0 if the sketch calls these functions.

    Use it in a test module as ``gates = [no_calls("delay", "delayMicroseconds")]``.
    """

    def check_source(source: str) -> None:
        forbid_calls(source, *names)

    check_source.__name__ = "no_calls_" + "_".join(names)
    return check_source
