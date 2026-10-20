"""Base class for Arduino question graders, in the style of PrairieLearn's cgrader.

A question's tests/test.py subclasses ArduinoGrader, implements tests() and
calls start(). Compilation and simulation run as an unprivileged user that
cannot read /grade, so a sketch cannot include the tests or other grading data.
"""

import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import traceback

from .simulation import SimulationStopped, Trace
from .source import find_calls

GRADE_DIR = Path("/grade")
WORK_DIR = Path("/tmp/arduinograder")
SANDBOX_USER = "sbuser"
MAX_COMPILE_LOG = 4000

TIMEOUT_MESSAGE = (
    "Grading took longer than expected on the server, so this submission was not "
    "graded. Please submit again."
)
INTERNAL_ERROR_MESSAGE = (
    "The grader failed unexpectedly, so this submission was not graded. Please submit "
    "again; if this keeps happening, tell your instructor."
)


class Ungradable(Exception):
    """Grading cannot run; PrairieLearn does not count the attempt."""


class StopGrading(Exception):
    """Stop grading with a score of zero and this message for the student."""


class Check:
    """Collects the failed expectations of one test."""

    def __init__(self):
        self.failures = []

    def expect(self, condition, message):
        if not condition:
            self.failures.append(message)
        return bool(condition)

    def fail(self, message):
        self.failures.append(message)


class ArduinoGrader:
    # Submitted file to grade. By default, sketch.ino (from a Velxio project)
    # or the only .ino file submitted.
    sketch_file = None
    # Wall-clock budget for compiling and simulating. Keep it below the
    # question's externalGradingOptions.timeout.
    time_budget_s = 45

    def __init__(self, grade_dir=GRADE_DIR, work_dir=WORK_DIR):
        self.grade_dir = Path(grade_dir)
        self.work_dir = Path(work_dir)
        self.results = {"gradable": True, "score": 0.0, "message": "", "tests": []}
        self.data = {}
        self.params = {}
        self._deadline = None
        self._source = None
        self._runs = 0

    def tests(self):
        raise NotImplementedError

    def start(self):
        self._deadline = time.monotonic() + self.time_budget_s
        stopped = False
        try:
            self._prepare()
            self.tests()
        except StopGrading as stop:
            stopped = True
            self.add_message(str(stop))
        except Ungradable as error:
            self.results["gradable"] = False
            self.add_message(str(error))
        except Exception:
            traceback.print_exc()
            self.results["gradable"] = False
            self.add_message(INTERNAL_ERROR_MESSAGE)
        finally:
            self._save(stopped)

    # -- Results --------------------------------------------------------------

    def add_message(self, message):
        self.results["message"] = "\n\n".join(
            part for part in [self.results["message"], message] if part
        )

    @contextlib.contextmanager
    def test(self, name, points, *, description=""):
        """Record one test, all or nothing: full points if every expectation holds."""
        check = Check()
        try:
            yield check
        except SimulationStopped as stopped:
            check.fail(str(stopped))
        self.results["tests"].append(
            {
                "name": name,
                "description": description,
                "points": 0 if check.failures else points,
                "max_points": points,
                "message": "\n".join(check.failures),
            }
        )

    def _save(self, stopped):
        tests = self.results["tests"]
        total = sum(test["max_points"] for test in tests)
        earned = sum(test["points"] for test in tests)
        self.results["score"] = 0.0 if stopped or not total else earned / total
        results = self.grade_dir / "results"
        results.mkdir(parents=True, exist_ok=True)
        (results / "results.json").write_text(
            json.dumps(self.results), encoding="utf-8"
        )

    # -- Sandbox ----------------------------------------------------------------

    def _prepare(self):
        data_file = self.grade_dir / "data/data.json"
        if data_file.is_file():
            self.data = json.loads(data_file.read_text(encoding="utf-8"))
            self.params = self.data.get("params", {})
        self._sandboxed = os.geteuid() == 0
        if self._sandboxed:
            for path in [self.grade_dir, *self.grade_dir.rglob("*")]:
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode & 0o700)
        shutil.rmtree(self.work_dir, ignore_errors=True)
        for name in ["sketch", "home", "user", "downloads", "cache"]:
            (self.work_dir / name).mkdir(parents=True)
        if self._sandboxed:
            shutil.chown(self.work_dir, SANDBOX_USER, SANDBOX_USER)
            for path in self.work_dir.rglob("*"):
                shutil.chown(path, SANDBOX_USER, SANDBOX_USER)
        self._env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(self.work_dir / "home"),
            "LANG": "C.UTF-8",
            "ARDUINO_DIRECTORIES_DATA": os.environ.get(
                "ARDUINO_DIRECTORIES_DATA", "/opt/arduino/data"
            ),
            "ARDUINO_DIRECTORIES_USER": str(self.work_dir / "user"),
            "ARDUINO_DIRECTORIES_DOWNLOADS": str(self.work_dir / "downloads"),
            "ARDUINO_BUILD_CACHE_PATH": str(self.work_dir / "cache"),
            "ARDUINO_UPDATER_ENABLE_NOTIFICATION": "false",
            "ARDUINO_METRICS_ENABLED": "false",
        }

    def _run(self, args):
        """Run a command as the sandbox user within the remaining time budget."""
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise Ungradable(TIMEOUT_MESSAGE)
        user = {}
        if self._sandboxed:
            user = {"user": SANDBOX_USER, "group": SANDBOX_USER, "extra_groups": []}
        process = subprocess.Popen(
            args,
            cwd=self.work_dir,
            env=self._env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            **user,
        )
        try:
            output, _ = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise Ungradable(TIMEOUT_MESSAGE) from None
        return process.returncode, output.decode("utf-8", "replace")

    def _write(self, path, text):
        path.write_text(text, encoding="utf-8")
        if self._sandboxed:
            shutil.chown(path, SANDBOX_USER, SANDBOX_USER)

    # -- Submission ---------------------------------------------------------------

    def _sketch_path(self):
        student = self.grade_dir / "student"
        if self.sketch_file:
            candidates = [student / self.sketch_file]
        elif (student / "sketch.ino").is_file():
            candidates = [student / "sketch.ino"]
        else:
            candidates = sorted(student.glob("*.ino"))
        if len(candidates) != 1 or not candidates[0].is_file():
            name = self.sketch_file or "an Arduino sketch (.ino file)"
            raise Ungradable(f"No submission was found. Submit {name} and try again.")
        return candidates[0]

    @property
    def sketch_name(self):
        return self._sketch_path().name

    @property
    def source(self):
        """The submitted sketch's text."""
        if self._source is None:
            self._source = self._sketch_path().read_text(
                encoding="utf-8", errors="replace"
            )
        return self._source

    def forbid_calls(self, *names):
        """Stop with a score of zero if the sketch calls any of these functions."""
        calls = find_calls(self.source, names)
        if calls:
            listed = "\n".join(
                f"    line {call.line}: {call.text}" for call in calls[:3]
            )
            names = ", ".join(sorted({f"{call.name}()" for call in calls}))
            raise StopGrading(
                f"Your sketch calls {names}, which this question does not allow:\n{listed}"
            )

    def compile(self):
        """Compile the sketch for the Uno and return the firmware path.

        A sketch that does not compile stops grading with a score of zero.
        """
        sketch = self.work_dir / "sketch/sketch.ino"
        self._write(sketch, self.source)
        build = self.work_dir / "build"
        code, log = self._run(
            [
                "arduino-cli", "compile", "--no-color", "--fqbn", "arduino:avr:uno",
                "--build-path", str(build), str(sketch.parent),
            ]
        )  # fmt: skip
        if code != 0:
            raise StopGrading("Your sketch did not compile.\n\n" + self._clean_log(log))
        firmware = build / "sketch.ino.elf"
        if not firmware.is_file():
            raise RuntimeError(f"arduino-cli produced no firmware:\n{log}")
        return firmware

    def _clean_log(self, log):
        log = re.sub(r"\x1b\[[0-9;]*m", "", log)
        log = log.replace(str(self.work_dir / "sketch/sketch.ino"), self.sketch_name)
        log = log.replace(str(self.work_dir), "")
        noise = re.compile(r"^(Sketch uses|Global variables use|Used platform|Used library|"
                           r"arduino:avr|Error during build|exit status)")  # fmt: skip
        lines = [
            line for line in log.splitlines() if line.strip() and not noise.match(line)
        ]
        text = "\n".join(lines)
        if len(text) > MAX_COMPILE_LOG:
            text = text[:MAX_COMPILE_LOG] + "\n[compiler output truncated]"
        return text

    # -- Simulation ---------------------------------------------------------------

    def simulate(self, firmware, scenario):
        """Run the firmware from reset through the scenario and return its Trace."""
        self._runs += 1
        scenario_file = self.work_dir / f"scenario-{self._runs}.txt"
        trace_file = self.work_dir / f"trace-{self._runs}.txt"
        self._write(scenario_file, scenario.to_text())
        code, output = self._run(
            ["avrsim", str(firmware), str(scenario_file), str(trace_file)]
        )
        if code != 0:
            raise RuntimeError(f"avrsim failed with status {code}:\n{output}")
        return Trace(trace_file.read_text(encoding="utf-8"), scenario)
