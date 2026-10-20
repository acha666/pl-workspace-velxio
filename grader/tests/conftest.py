import itertools
import time
from pathlib import Path

import pytest

from arduinograder import ArduinoGrader

_runs = itertools.count()


def prepared_grader(tmp_path, source):
    """A grader for one submitted sketch, ready to compile and simulate."""
    run = next(_runs)
    grade = tmp_path / f"grade-{run}"
    (grade / "student").mkdir(parents=True)
    (grade / "student/sketch.ino").write_text(source)
    # The sandbox user must reach the work directory, so keep it out of tmp_path.
    grader = ArduinoGrader(
        grade_dir=grade, work_dir=Path(f"/tmp/arduinograder-test-{run}")
    )
    grader._deadline = time.monotonic() + 120
    grader._prepare()
    return grader


@pytest.fixture
def simulate(tmp_path):
    """Compile a sketch and simulate it through a scenario."""

    def run(source, scenario):
        grader = prepared_grader(tmp_path, source)
        return grader.simulate(grader.compile(), scenario)

    return run
