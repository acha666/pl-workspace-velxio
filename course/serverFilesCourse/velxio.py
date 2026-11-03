"""Add a sketch preview from the submitted project snapshot for manual grading."""

import base64
import binascii
import json

import prairielearn as pl

MAX_PROJECT_BYTES = 1024 * 1024
MAX_SKETCH_BYTES = 128 * 1024


def extract_sketch(encoded_project):
    """Extract exactly one Uno sketch, preserving its original text."""
    if not isinstance(encoded_project, str):
        raise ValueError("Missing project contents.")
    if len(encoded_project) > 4 * ((MAX_PROJECT_BYTES + 2) // 3):
        raise ValueError("The project exceeds the 1 MiB limit.")
    raw = base64.b64decode(encoded_project, validate=True)
    if len(raw) > MAX_PROJECT_BYTES:
        raise ValueError("The project exceeds the 1 MiB limit.")
    project = json.loads(raw.decode("utf-8"))
    if not isinstance(project, dict) or project.get("format") != "velxio-project":
        raise ValueError("Expected a Velxio project.")
    if type(project.get("version")) is not int or project["version"] != 1:
        raise ValueError("Unsupported Velxio project version.")
    boards = project.get("boards")
    if not isinstance(boards, list) or len(boards) != 1:
        raise ValueError("Expected one Arduino Uno.")
    board = boards[0]
    if not isinstance(board, dict) or board.get("boardKind") != "arduino-uno":
        raise ValueError("Expected one Arduino Uno.")
    groups = project.get("fileGroups")
    group_id = board.get("activeFileGroupId")
    if (
        not isinstance(groups, dict)
        or len(groups) != 1
        or not isinstance(group_id, str)
    ):
        raise ValueError("Expected one file group.")
    files = groups.get(group_id)
    if not isinstance(files, list) or len(files) != 1:
        raise ValueError("Expected one sketch.ino file.")
    sketch = files[0]
    if not isinstance(sketch, dict) or sketch.get("name") != "sketch.ino":
        raise ValueError("Expected one sketch.ino file.")
    source = sketch.get("content")
    if not isinstance(source, str):
        raise ValueError("The sketch must contain text.")
    if len(source.encode("utf-8")) > MAX_SKETCH_BYTES:
        raise ValueError("The sketch exceeds the 128 KiB limit.")
    return source


def parse(data):
    # PrairieLearn collects gradedFiles before parse(). Never read the live workspace.
    submitted_files = data["submitted_answers"].get("_files", [])
    if not isinstance(submitted_files, list) or any(
        not isinstance(file, dict) for file in submitted_files
    ):
        data["format_errors"].setdefault("_files", []).append(
            "Invalid submitted files."
        )
        return

    # Discard any supplied or previously derived preview, even on invalid submissions.
    data["submitted_answers"]["_files"] = [
        file for file in submitted_files if file.get("name") != "sketch.ino"
    ]
    projects = [file for file in submitted_files if file.get("name") == "project.vlx"]
    if len(projects) != 1:
        data["format_errors"].setdefault("_files", []).append(
            "Open the workspace, wait until the save icon above its file list is green, "
            "then click Save on PrairieLearn."
        )
        return

    try:
        source = extract_sketch(projects[0].get("contents"))
    except (ValueError, UnicodeError, binascii.Error, RecursionError):
        data["format_errors"].setdefault("_files", []).append(
            "The project could not be read. Keep one Arduino Uno with one sketch.ino "
            "file, save in the workspace, then save again on PrairieLearn."
        )
        return

    pl.add_submitted_file(data, "sketch.ino", raw_contents=source)
    # Present the extracted sketch before the project snapshot.
    data["submitted_answers"]["_files"].sort(
        key=lambda file: file.get("name") != "sketch.ino"
    )
