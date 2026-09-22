"""Submission snapshots and starter projects used by the reusable questions."""

import base64
import copy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "templates/questions/arduino"


def encode(project):
    raw = json.dumps(project, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def add_submitted_file(data, name, *, raw_contents):
    data["submitted_answers"]["_files"].append(
        {
            "name": name,
            "contents": base64.b64encode(raw_contents.encode("utf-8")).decode("ascii"),
        }
    )


spec = importlib.util.spec_from_file_location(
    "velxio", ROOT / "templates/serverFilesCourse/velxio.py"
)
velxio = importlib.util.module_from_spec(spec)
with patch.dict(
    sys.modules,
    {"prairielearn": types.SimpleNamespace(add_submitted_file=add_submitted_file)},
):
    spec.loader.exec_module(velxio)


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.project = json.loads(
            (QUESTIONS / "blink/workspace/project.vlx").read_text()
        )

    def submit(self, files):
        data = {"submitted_answers": {"_files": files}, "format_errors": {}}
        velxio.parse(data)
        return data

    def test_preview_comes_from_snapshot_and_replaces_supplied_source(self):
        source = "// Saved snapshot: café\r\nvoid setup() {}\r\nvoid loop() {}\n"
        self.project["fileGroups"]["group-arduino-uno"][0]["content"] = source
        project_file = {"name": "project.vlx", "contents": encode(self.project)}
        data = self.submit([project_file, {"name": "sketch.ino", "contents": "forged"}])
        self.assertEqual(data["format_errors"], {})
        files = data["submitted_answers"]["_files"]
        self.assertEqual(files[0], project_file)
        self.assertEqual(base64.b64decode(files[1]["contents"]).decode(), source)
        velxio.parse(data)
        self.assertEqual(len(data["submitted_answers"]["_files"]), 2)

    def test_missing_duplicate_and_invalid_files_fail_without_trusting_preview(self):
        project_file = {"name": "project.vlx", "contents": encode(self.project)}
        for files in [
            [],
            [project_file, project_file],
            [None],
            None,
            {},
            [
                {"name": "project.vlx", "contents": "not base64"},
                {"name": "sketch.ino", "contents": "forged"},
            ],
        ]:
            with self.subTest(files=files):
                data = self.submit(files)
                self.assertIn("_files", data["format_errors"])
                if isinstance(data["submitted_answers"]["_files"], list):
                    self.assertFalse(
                        any(
                            isinstance(file, dict) and file.get("name") == "sketch.ino"
                            for file in data["submitted_answers"]["_files"]
                        )
                    )

    def test_unsupported_project_shapes_fail(self):
        mutations = [
            {"version": True},
            {"version": 2},
            {"format": "other"},
            {"boards": []},
            {"boards": [self.project["boards"][0]] * 2},
            {"boards": [{"boardKind": "esp32"}]},
            {"fileGroups": {}},
            {"fileGroups": {"group-arduino-uno": []}},
            {
                "fileGroups": {
                    "group-arduino-uno": [{"name": "other.ino", "content": ""}]
                }
            },
            {
                "fileGroups": {
                    "group-arduino-uno": [{"name": "sketch.ino", "content": None}]
                }
            },
        ]
        for change in mutations:
            with self.subTest(change=change):
                project = copy.deepcopy(self.project)
                project.update(change)
                data = self.submit(
                    [{"name": "project.vlx", "contents": encode(project)}]
                )
                self.assertIn("_files", data["format_errors"])

    def test_size_limits_and_invalid_encoding_fail(self):
        oversized = base64.b64encode(b" " * (velxio.MAX_PROJECT_BYTES + 1)).decode()
        too_long = copy.deepcopy(self.project)
        too_long["fileGroups"]["group-arduino-uno"][0]["content"] = "é" * (
            velxio.MAX_SKETCH_BYTES // 2 + 1
        )
        for contents in [
            oversized,
            encode(too_long),
            base64.b64encode(b"\xff").decode(),
            base64.b64encode(b"[]").decode(),
            None,
        ]:
            with self.subTest(length=len(contents) if contents else 0):
                data = self.submit([{"name": "project.vlx", "contents": contents}])
                self.assertIn("_files", data["format_errors"])


class TemplateTests(unittest.TestCase):
    def test_questions_collect_one_project_and_expose_starter_preview(self):
        for question in sorted(QUESTIONS.iterdir()):
            with self.subTest(question=question.name):
                info = json.loads((question / "info.json").read_text())
                project = json.loads((question / "workspace/project.vlx").read_text())
                self.assertEqual(info["gradingMethod"], "Manual")
                self.assertEqual(
                    info["workspaceOptions"]["gradedFiles"], ["project.vlx"]
                )
                self.assertFalse(info["workspaceOptions"]["enableNetworking"])
                source = velxio.extract_sketch(encode(project))
                self.assertIn("TODO", source)
                self.assertNotIn("digitPatterns", source)
                self.assertEqual(
                    sorted(path.name for path in (question / "workspace").iterdir()),
                    ["project.vlx"],
                )

    def test_seven_segment_connections_have_individual_current_limiting_resistors(self):
        project = json.loads(
            (QUESTIONS / "sevenSegment/workspace/project.vlx").read_text()
        )
        components = {part["id"]: part for part in project["components"]}
        connections = {
            frozenset(
                (end["componentId"], end["pinName"])
                for end in (wire["start"], wire["end"])
            )
            for wire in project["wires"]
        }
        self.assertEqual(components["display"]["properties"]["common"], "cathode")
        self.assertIn(
            frozenset({("display", "COM.1"), ("arduino-uno", "GND.1")}), connections
        )
        for pin, segment in enumerate("ABCDEFG", 2):
            resistor = f"resistor_{segment.lower()}"
            self.assertEqual(components[resistor]["properties"]["value"], "220")
            self.assertIn(
                frozenset({("arduino-uno", str(pin)), (resistor, "1")}), connections
            )
            self.assertIn(
                frozenset({(resistor, "2"), ("display", segment)}), connections
            )


if __name__ == "__main__":
    unittest.main()
