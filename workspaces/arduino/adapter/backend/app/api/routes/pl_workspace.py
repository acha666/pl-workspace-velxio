"""Opt-in PrairieLearn persistence for the native Velxio .vlx project format.

Only project.vlx is authoritative. PrairieLearn collects that one atomic file;
the question's parse hook derives its .ino preview from the collected snapshot.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from starlette.requests import Request


MAX_PROJECT_BYTES = 1024 * 1024
MAX_CODE_BYTES = 128 * 1024
router = APIRouter()
# The entrypoint runs one worker, as required by upstream's compile job registry.
_file_lock = threading.Lock()


class NativeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SketchFile(NativeModel):
    name: Literal["sketch.ino"]
    content: str

    @field_validator("content")
    @classmethod
    def source_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_CODE_BYTES:
            raise ValueError("sketch.ino exceeds 128 KiB")
        return value


class UnoBoard(NativeModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(min_length=1)
    boardKind: Literal["arduino-uno"]
    activeFileGroupId: str = Field(min_length=1)


class VlxProject(NativeModel):
    """Native VlxPayload restricted to the Arduino workspace's supported board."""

    model_config = ConfigDict(extra="allow")
    format: Literal["velxio-project"]
    version: Literal[1]
    exportedAt: str
    boards: list[UnoBoard] = Field(min_length=1, max_length=1)
    fileGroups: dict[str, list[SketchFile]]
    # Component properties evolve upstream. Preserve their native JSON rather
    # than inventing an alternate circuit format or dropping unknown metadata.
    components: list[dict[str, Any]]
    wires: list[dict[str, Any]]
    activeBoardId: str

    @model_validator(mode="after")
    def one_sketch(self):
        board = self.boards[0]
        if self.activeBoardId != board.id:
            raise ValueError("activeBoardId must reference the Uno board")
        if set(self.fileGroups) != {board.activeFileGroupId}:
            raise ValueError("The workspace supports the Uno's single file group")
        if len(self.fileGroups[board.activeFileGroupId]) != 1:
            raise ValueError("The file group must contain exactly sketch.ino")
        return self


class SaveRequest(NativeModel):
    project: VlxProject
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


def project_path() -> Path:
    return Path(os.environ.get("WORKSPACE_DIR", "/workspace")) / "project.vlx"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_project() -> tuple[dict, str]:
    """Caller holds _file_lock; a missing PrairieLearn seed is never replaced."""
    try:
        fd = os.open(project_path(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise OSError("project.vlx must be a regular file")
            data = source.read(MAX_PROJECT_BYTES + 1)
    except FileNotFoundError as exc:
        raise HTTPException(
            503,
            "project.vlx is missing. PrairieLearn must seed the workspace before it opens.",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            503, "Cannot read project.vlx. Check workspace permissions."
        ) from exc
    if len(data) > MAX_PROJECT_BYTES:
        raise HTTPException(413, "project.vlx exceeds the 1 MiB project limit.")
    try:
        parsed = json.loads(data)
        VlxProject.model_validate(parsed)
        # Disallow non-JSON floating-point constants even inside free-form
        # component properties, which Pydantic deliberately preserves.
        json.dumps(parsed, allow_nan=False)
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(
            422, "The saved project.vlx is not a supported single-Uno project."
        ) from exc
    return parsed, digest(data)


@router.get("")
def load_workspace():
    with _file_lock:
        project, revision = read_project()
    return {"project": project, "revision": revision}


@router.put("")
def save_workspace(payload: SaveRequest):
    try:
        data = (
            json.dumps(
                payload.project.model_dump(exclude_unset=True),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(
            422, "Project properties must contain valid UTF-8 JSON values."
        ) from exc
    if len(data) > MAX_PROJECT_BYTES:
        raise HTTPException(413, "project.vlx exceeds the 1 MiB project limit.")
    with _file_lock:
        _, revision = read_project()
        # A write may have completed before its response was lost. Confirm an
        # identical retry without replacing the file or rejecting it as a conflict.
        if digest(data) == revision:
            return {"revision": revision}
        if revision != payload.revision:
            raise HTTPException(
                409,
                "The saved project changed in another session. Export your local work, then reload.",
            )
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=project_path().parent, prefix=".project-save-", delete=False
            ) as target:
                temporary = Path(target.name)
                os.fchmod(target.fileno(), 0o644)
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, project_path())
            directory_fd = os.open(project_path().parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise HTTPException(
                503,
                "Could not save project.vlx. Check workspace disk space and permissions.",
            ) from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {"revision": digest(data)}


class WorkspaceOnlyMiddleware:
    """Limit the existing API in exam workspaces; compilation stays upstream."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        path, method = scope["path"], scope["method"]
        allowed = (
            (path == "/api/pl-workspace" and method in {"GET", "PUT"})
            or (path in {"/api/compile/", "/api/compile/start"} and method == "POST")
            or (path in {"/api/compile/boards", "/health"} and method == "GET")
            or (
                re.fullmatch(r"/api/compile/status/[0-9a-f]{32}", path) is not None
                and method == "GET"
            )
        )
        if not allowed:
            await JSONResponse(
                {"detail": "This endpoint is unavailable in the course workspace."}, 404
            )(scope, receive, send)
            return
        if method in {"PUT", "POST"}:
            request = Request(scope, receive)
            if request.headers.get("sec-fetch-site") == "cross-site":
                await JSONResponse(
                    {"detail": "Cross-site writes are not allowed."}, 403
                )(scope, receive, send)
                return
            if (
                request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                await JSONResponse(
                    {"detail": "Use Content-Type: application/json."}, 415
                )(scope, receive, send)
                return
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_PROJECT_BYTES:
                    await JSONResponse({"detail": "The request exceeds 1 MiB."}, 413)(
                        scope, receive, send
                    )
                    return
            if path.startswith("/api/compile/"):
                try:
                    data = json.loads(body)
                    if (
                        not isinstance(data, dict)
                        or data.get("board_fqbn", "arduino:avr:uno")
                        != "arduino:avr:uno"
                    ):
                        raise ValueError(
                            "Only the preinstalled Arduino Uno toolchain is available."
                        )
                    files = data.get("files")
                    if not isinstance(files, list) or len(files) != 1:
                        raise ValueError("Compile exactly one sketch.ino file.")
                    SketchFile.model_validate(files[0])
                    if (
                        data.get("libraries")
                        or data.get("spiffs_files")
                        or data.get("language") not in (None, "arduino")
                    ):
                        raise ValueError(
                            "External libraries and other board languages are unavailable."
                        )
                except (ValueError, UnicodeError, ValidationError):
                    await JSONResponse(
                        {
                            "detail": "This question compiles one sketch.ino for Arduino Uno with preinstalled libraries only."
                        },
                        422,
                    )(scope, receive, send)
                    return

            original_receive = receive
            replayed = False

            async def replay():
                nonlocal replayed
                if replayed:
                    return await original_receive()
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            receive = replay

        async def no_cache(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"cache-control", b"no-store")
                )
            await send(message)

        await self.app(scope, receive, no_cache)


def register(app: FastAPI) -> None:
    app.include_router(router, prefix="/api/pl-workspace", tags=["PrairieLearn"])
    app.add_middleware(WorkspaceOnlyMiddleware)
