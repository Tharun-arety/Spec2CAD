"""Safe host launcher for the fixed FreeCAD worker entrypoint."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from pydantic import ValidationError

from .freecad_worker_contracts import (
    FreeCADWorkerDiagnostic,
    FreeCADWorkerRequest,
    FreeCADWorkerResponse,
    WorkerStatus,
)


WORKER_ENTRYPOINT = Path(__file__).with_name("freecad_worker_generic.py").resolve()
WORKER_BOOTSTRAP = (
    "import os,runpy,sys;"
    "sys.argv=[os.environ['CADAICO_FREECAD_ENTRYPOINT']];"
    "runpy.run_path(os.environ['CADAICO_FREECAD_ENTRYPOINT'],run_name='__main__')"
)
_COMMON_EXECUTABLES = (
    Path(r"C:\Program Files\FreeCAD 1.0\bin\FreeCADCmd.exe"),
    Path(r"C:\Program Files\FreeCAD 0.21\bin\FreeCADCmd.exe"),
    Path.home() / ".codex" / "runtimes" / "freecad-r1" / "Library" / "bin" / "FreeCADCmd.exe",
    Path.home() / ".codex" / "runtimes" / "freecad-r1" / "bin" / "FreeCADCmd.exe",
)


class FreeCADWorkerUnavailable(RuntimeError):
    pass


def discover_freecad_cmd(explicit: Path | None = None) -> Path:
    candidates = []
    if explicit is not None:
        candidates.append(Path(explicit))
    configured = os.environ.get("FREECAD_CMD")
    if configured:
        candidates.append(Path(configured))
    candidates.extend(_COMMON_EXECUTABLES)
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file() and resolved.name.lower() in {
            "freecadcmd.exe", "freecadcmd"
        }:
            return resolved
    raise FreeCADWorkerUnavailable(
        "FreeCADCmd was not found; configure FREECAD_CMD or install the isolated runtime"
    )


def _failure(
    request: FreeCADWorkerRequest,
    code: str,
    message: str,
) -> FreeCADWorkerResponse:
    return FreeCADWorkerResponse(
        request_id=request.request_id,
        operation=request.operation,
        status=WorkerStatus.FAILED,
        diagnostics=(FreeCADWorkerDiagnostic(code=code, message=message),),
    )


def run_freecad_worker(
    request: FreeCADWorkerRequest,
    *,
    executable: Path | None = None,
    timeout_seconds: float = 30.0,
) -> FreeCADWorkerResponse:
    """Run a validated message through a fixed script with no shell involved."""
    command = discover_freecad_cmd(executable)
    if timeout_seconds <= 0:
        raise ValueError("worker timeout must be positive")
    with tempfile.TemporaryDirectory(prefix="cadaico-freecad-") as temp_dir:
        work = Path(temp_dir)
        user_home = work / "user"
        user_data = user_home / ".FreeCAD"
        user_temp = user_home / "temp"
        for directory in (user_home, user_data, user_temp):
            directory.mkdir(parents=True, exist_ok=True)
        request_path = work / "request.json"
        response_path = work / "response.json"
        request_payload = request.model_dump(mode="json")
        request_payload = {
            key: value for key, value in request_payload.items()
            if value is not None
        }
        request_path.write_text(
            json.dumps(request_payload, separators=(",", ":")), encoding="utf-8"
        )
        environment = os.environ.copy()
        runtime_prefix = (
            command.parent.parent.parent
            if command.parent.name.lower() == "bin"
            and command.parent.parent.name.lower() == "library"
            else command.parent.parent
        )
        runtime_paths = (
            runtime_prefix,
            runtime_prefix / "Library" / "bin",
            runtime_prefix / "Library" / "usr" / "bin",
            runtime_prefix / "Scripts",
            runtime_prefix / "bin",
        )
        environment.update({
            "PATH": os.pathsep.join(str(path) for path in runtime_paths)
            + os.pathsep + environment.get("PATH", ""),
            "CONDA_PREFIX": str(runtime_prefix),
            "FREECAD_USER_HOME": str(user_home),
            "FREECAD_USER_DATA": str(user_data),
            "FREECAD_USER_TEMP": str(user_temp),
            "APPDATA": str(user_data),
            "LOCALAPPDATA": str(user_data),
            "CADAICO_FREECAD_REQUEST": str(request_path),
            "CADAICO_FREECAD_RESPONSE": str(response_path),
            "CADAICO_FREECAD_ENTRYPOINT": str(WORKER_ENTRYPOINT),
        })
        try:
            completed = subprocess.run(
                [
                    str(command), "-c", WORKER_BOOTSTRAP,
                ],
                shell=False,
                cwd=str(work),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
                env=environment,
            )
        except subprocess.TimeoutExpired:
            return _failure(request, "timeout", f"FreeCAD worker exceeded {timeout_seconds:g}s")
        if not response_path.is_file():
            summary = (completed.stderr or completed.stdout or "").strip()[-500:]
            return _failure(
                request,
                "worker_failure",
                f"FreeCAD worker exited {completed.returncode} without a response"
                + (f": {summary}" if summary else ""),
            )
        try:
            response = FreeCADWorkerResponse.model_validate_json(
                response_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, json.JSONDecodeError) as exc:
            return _failure(request, "malformed_response", str(exc))
        if response.request_id != request.request_id or response.operation is not request.operation:
            return _failure(request, "malformed_response", "response identity does not match request")
        if completed.returncode != 0 and response.status is WorkerStatus.SUCCEEDED:
            return _failure(
                request, "worker_failure",
                f"worker reported success but exited {completed.returncode}",
            )
        return response
