"""Static checks on sketch source using the tree-sitter C++ grammar."""

from collections import namedtuple

import tree_sitter_cpp
from tree_sitter import Language, Parser

from ..grader import StopGrading

Call = namedtuple("Call", "name line text")
_PARSER = Parser(Language(tree_sitter_cpp.language()))


def find_calls(source, names):
    """Calls to the named functions, ignoring comments and string literals.

    Matches plain and ::-qualified calls such as delay(10) and ::delay(10).
    Calls hidden behind macros or function pointers are not detected.
    """
    names = set(names)
    data = source.encode("utf-8")
    lines = source.split("\n")  # tree-sitter rows split on "\n" only
    calls = []
    stack = [_PARSER.parse(data).root_node]
    while stack:
        node = stack.pop()
        if node.type == "call_expression":
            function = node.child_by_field_name("function")
            if function is not None and function.type == "qualified_identifier":
                function = function.child_by_field_name("name")
            if function is not None and function.type == "identifier":
                name = function.text.decode("utf-8")
                if name in names:
                    line = node.start_point[0]
                    text = lines[line].strip() if line < len(lines) else ""
                    calls.append(Call(name, line + 1, text))
        stack.extend(reversed(node.children))
    return sorted(calls, key=lambda call: call.line)


def forbid_calls(source, *names):
    """Stop grading with a score of zero if the source calls any of these functions."""
    calls = find_calls(source, names)
    if calls:
        listed = "\n".join(f"    line {call.line}: {call.text}" for call in calls[:3])
        names = ", ".join(sorted({f"{call.name}()" for call in calls}))
        raise StopGrading(
            f"Your sketch calls {names}, which this question does not allow:\n{listed}"
        )
