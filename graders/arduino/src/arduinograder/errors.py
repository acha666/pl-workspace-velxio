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
"""Shown when the grader itself failed outside of a test."""


class Ungradable(Exception):
    """The submission cannot be graded, so PrairieLearn must not count the attempt.

    The message is for the student, as when no sketch was submitted or the server
    was too slow to finish within the time budget.
    """


class ConfigurationError(Exception):
    """The test module is set up wrongly, so no submission can be graded with it.

    The submission is reported as ungradable with the internal error message, and
    the cause goes to the log for the author to fix.
    """


class StopGrading(Exception):
    """Stop grading with a score of zero and a message for the student.

    Gates raise it to reject a submission, and ``CompileError`` subclasses it.
    """
