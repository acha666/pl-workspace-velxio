"""PrairieLearn's external grader layout: ``/grade`` in, ``results/results.json`` out.

PrairieLearn starts the grader image with the submitted files under
``/grade/student``, the question's ``tests/`` and ``data/data.json`` beside
them, and reads ``/grade/results/results.json`` when the container exits.
``Submission`` reads that layout, ``Results`` writes it, and ``protect()``
keeps it from the sandbox user.
"""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path
from typing import Any, Final, TypedDict

from .errors import INTERNAL_ERROR_MESSAGE, Ungradable
from .rubric import ItemResult, TestResultDict

GRADE_DIR: Final = Path("/grade")
"""PrairieLearn's grading directory inside the container."""


class ResultsDict(TypedDict):
    """PrairieLearn's ``results.json``."""

    gradable: bool
    score: float
    message: str
    tests: list[TestResultDict]


class Submission:
    """What the student submitted, as PrairieLearn lays it out under ``grade_dir``.

    Attributes:
        grade_dir: PrairieLearn's grading directory.
        sketch_file: The file to grade, or ``None`` to find it.
        data: PrairieLearn's ``data.json``, or an empty dict without one.
        params: The question's params from ``data``.
    """

    def __init__(
        self, grade_dir: str | os.PathLike[str], *, sketch_file: str | None = None
    ) -> None:
        """Read ``data.json``; the submitted files are read on demand.

        Args:
            grade_dir: The grading directory with ``student/`` and ``data/``.
            sketch_file: The submitted file to grade; by default ``sketch.ino``,
                else the only ``.ino`` file.
        """
        self.grade_dir = Path(grade_dir)
        self.sketch_file = sketch_file
        self.data: dict[str, Any] = {}
        data_file = self.grade_dir / "data/data.json"
        if data_file.is_file():
            self.data = json.loads(data_file.read_text(encoding="utf-8"))
        self.params: dict[str, Any] = self.data.get("params", {})
        self._source: str | None = None

    @property
    def student_dir(self) -> Path:
        """The directory holding the submitted files."""
        return self.grade_dir / "student"

    @property
    def files(self) -> list[str]:
        """The names of the submitted files."""
        if not self.student_dir.is_dir():
            return []
        return sorted(path.name for path in self.student_dir.iterdir())

    def read(self, name: str) -> str:
        """Return a submitted file's text."""
        return (self.student_dir / name).read_text(encoding="utf-8", errors="replace")

    @property
    def sketch_path(self) -> Path:
        """The submitted sketch.

        Raises:
            Ungradable: If there is no sketch to grade, with a message for the student.
        """
        if self.sketch_file:
            candidates = [self.student_dir / self.sketch_file]
        elif (self.student_dir / "sketch.ino").is_file():
            candidates = [self.student_dir / "sketch.ino"]
        else:
            candidates = sorted(self.student_dir.glob("*.ino"))
        if len(candidates) != 1 or not candidates[0].is_file():
            name = self.sketch_file or "an Arduino sketch (.ino file)"
            raise Ungradable(f"No submission was found. Submit {name} and try again.")
        return candidates[0]

    @property
    def sketch_name(self) -> str:
        """The submitted sketch's file name."""
        return self.sketch_path.name

    @property
    def source(self) -> str:
        """The submitted sketch's text."""
        if self._source is None:
            self._source = self.sketch_path.read_text(encoding="utf-8", errors="replace")
        return self._source


class Results:
    """What goes into ``results.json``.

    Attributes:
        gradable: ``False`` when PrairieLearn must not count the attempt.
        stopped: ``True`` when grading stopped with zero points.
        message: Overall feedback for the student.
        items: The tests' results.
    """

    def __init__(self) -> None:
        """Start empty and gradable."""
        self.gradable = True
        self.stopped = False
        self.message = ""
        self.items: list[ItemResult] = []

    def add_message(self, text: str) -> None:
        """Append a paragraph to the overall feedback."""
        self.message = "\n\n".join(part for part in [self.message, text] if part)

    def add(self, item_result: ItemResult) -> None:
        """Record a test's result."""
        self.items.append(item_result)

    @property
    def score(self) -> float:
        """The share of points earned, 0 when stopped or without tests."""
        total = sum(item.max_points for item in self.items)
        if self.stopped or not total:
            return 0.0
        return sum(item.points for item in self.items) / total

    def to_dict(self) -> ResultsDict:
        """Return the ``results.json`` content."""
        return {
            "gradable": self.gradable,
            "score": self.score,
            "message": self.message,
            "tests": [item.to_dict() for item in self.items],
        }

    def write(self, grade_dir: str | os.PathLike[str]) -> None:
        """Write ``results/results.json`` under the grading directory.

        PrairieLearn cannot parse ``NaN`` or ``Infinity``, so a result holding
        one is written as ungradable with the internal error message instead.
        """
        path = Path(grade_dir) / "results/results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = json.dumps(self.to_dict(), allow_nan=False)
        except ValueError:
            traceback.print_exc()
            failed = Results()
            failed.gradable = False
            failed.add_message(INTERNAL_ERROR_MESSAGE)
            text = json.dumps(failed.to_dict())
        path.write_text(text, encoding="utf-8")


def protect(grade_dir: Path) -> None:
    """Make a grading directory's contents readable by their owner only.

    The grader runs as root and the sandbox user cannot read what is hidden
    this way, so a sketch cannot ``#include`` the tests or ``data.json``. The
    directory itself and its ``results/`` keep their modes, so whoever
    collects the results outside the container can still reach them.
    """
    for child in grade_dir.iterdir():
        if child.name == "results":
            continue
        for path in [child, *child.rglob("*")]:
            if not path.is_symlink():
                path.chmod(path.stat().st_mode & 0o700)
