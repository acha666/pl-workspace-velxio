"""Exceptions that end grading early, and the messages students then see."""

from typing import Final

TIMEOUT_MESSAGE: Final = (
    "Grading took longer than expected on the server, so this submission was not "
    "graded. Please submit again."
)
"""Shown when compiling and simulating overran the wall-clock budget."""

INTERNAL_ERROR_MESSAGE: Final = (
    "The grader failed unexpectedly, so this submission was not graded. Please submit "
    "again; if this keeps happening, tell your instructor."
)
"""Shown when the grader itself raised outside of a test."""


class Ungradable(Exception):
    """The submission cannot be graded, so PrairieLearn must not count the attempt.

    Raise it with a message for the student, for example when no sketch was
    submitted or the server was too slow to finish within the time budget.
    """


class StopGrading(Exception):
    """Stop grading with a score of zero and a message for the student.

    A gate raises it to reject a submission outright, and a compile error is
    reported through its subclass ``CompileError``.
    """
