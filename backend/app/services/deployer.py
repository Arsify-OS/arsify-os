"""
Deployer — runs a compiled project as a subprocess.

Workflow:
  1. Unzip project.zip to /tmp/arsify_deploy/{session_id}/
  2. Allocate a free port in 9000-9099 range
  3. Create a per-project venv (.venv/) and install requirements.txt
  4. Start uvicorn main:app via subprocess.Popen (non-blocking)
  5. Return {url, port, pid, status}

The Popen process is detached from the FastAPI request lifecycle —
killing pipeline_engine does not kill the deployed app (it's tracked
by PID and can be stopped via stop_deployment()).

Process state lives in two places:
  - In-memory: Deployer._deployments dict (lost on restart)
  - On-disk:   {project_dir}/deploy.json (survives restart)

Port allocation:
  - First free port in PORT_MIN..PORT_MAX is chosen via socket bind probe.
  - Already-deployed sessions reuse their previous port (if still bound).

Safety:
  - All subprocess calls have explicit timeouts.
  - Install step times out at 180s.
  - Health-check loop times out at 30s after server start.
"""
import os
import json
import shutil
import socket
import logging
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from urllib.request import urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

DEPLOY_BASE       = Path(os.environ.get("DEPLOY_BASE_PATH", "/tmp/arsify_deploy"))
PORT_MIN          = int(os.environ.get("DEPLOY_PORT_MIN", "9000"))
PORT_MAX          = int(os.environ.get("DEPLOY_PORT_MAX", "9099"))
INSTALL_TIMEOUT   = 180.0
HEALTH_TIMEOUT    = 30.0
HOST              = os.environ.get("DEPLOY_PUBLIC_HOST", "localhost")


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class DeploymentInfo:
    session_id: str
    status:     str            # "starting" | "running" | "failed" | "stopped"
    url:        str
    port:       int
    pid:        Optional[int]      = None
    error:      Optional[str]      = None
    log_path:   Optional[str]      = None
    started_at: Optional[float]    = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Helper functions ─────────────────────────────────────────────────────────

def _is_port_free(port: int) -> bool:
    """Try binding to (0.0.0.0, port). True if free."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _allocate_port(used_ports: set[int]) -> int:
    """First free port in PORT_MIN..PORT_MAX. Raises RuntimeError if none."""
    for p in range(PORT_MIN, PORT_MAX + 1):
        if p in used_ports:
            continue
        if _is_port_free(p):
            return p
    raise RuntimeError(
        f"No free port available in range {PORT_MIN}-{PORT_MAX}. "
        "Stop existing deployments first."
    )


def _wait_for_health(url: str, timeout: float = HEALTH_TIMEOUT) -> bool:
    """Poll url until 200 OK or timeout. Used after starting uvicorn."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2.0) as r:
                if r.status == 200:
                    return True
        except (URLError, ConnectionError, OSError):
            pass
        time.sleep(0.5)
    return False


# ── Deployer ─────────────────────────────────────────────────────────────────

class Deployer:
    """
    Manages deployed sub-applications.
    Singleton expected — instantiated once at app startup, stored on app.state.
    """

    def __init__(self, file_store):
        self.file_store = file_store
        self._deployments: dict[str, DeploymentInfo] = {}
        DEPLOY_BASE.mkdir(parents=True, exist_ok=True)
        # Reload existing deployment state from disk
        self._reload_from_disk()

    # ── Public API ─────────────────────────────────────────────────────────────

    def deploy_project(self, session_id: str) -> DeploymentInfo:
        """
        Full deploy flow. Returns DeploymentInfo with status="running" or "failed".
        Does NOT raise — errors are captured in DeploymentInfo.error.
        """
        logger.info(f"[{session_id}] Deployer: starting deployment")

        # Check if session already deployed and still alive
        existing = self._deployments.get(session_id)
        if existing and existing.pid and self._pid_alive(existing.pid):
            logger.info(
                f"[{session_id}] Deployer: already running on port {existing.port} "
                f"(pid={existing.pid})"
            )
            return existing

        # Locate project.zip from the session directory
        try:
            zip_path = Path(self.file_store.session_dir(session_id)) / "project.zip"
        except Exception as e:
            return self._fail(session_id, f"Could not resolve session dir: {e}")

        if not zip_path.exists():
            return self._fail(
                session_id,
                f"project.zip not found at {zip_path}. Run /compile first.",
            )

        # 1. Unzip into deployment directory
        try:
            project_dir = self._unzip(session_id, zip_path)
        except Exception as e:
            return self._fail(session_id, f"Unzip failed: {e}")

        # 2. Allocate port
        try:
            used = {d.port for d in self._deployments.values() if d.status == "running"}
            port = _allocate_port(used)
        except RuntimeError as e:
            return self._fail(session_id, str(e))

        # 3. Create venv + install
        try:
            self._create_venv_and_install(project_dir)
        except Exception as e:
            return self._fail(session_id, f"Dependency install failed: {e}")

        # 4. Start uvicorn subprocess
        try:
            pid, log_path = self._start_uvicorn(project_dir, port, session_id)
        except Exception as e:
            return self._fail(session_id, f"Failed to start uvicorn: {e}")

        # 5. Health check
        url = f"http://{HOST}:{port}"
        healthy = _wait_for_health(url)
        if not healthy:
            # Don't kill the process — log readable, return failed but include pid
            info = DeploymentInfo(
                session_id=session_id,
                status="failed",
                url=url,
                port=port,
                pid=pid,
                error=(
                    f"Server did not respond at {url} within {HEALTH_TIMEOUT}s. "
                    f"Check logs: {log_path}"
                ),
                log_path=str(log_path),
                started_at=time.time(),
            )
            self._deployments[session_id] = info
            self._persist(session_id, info, project_dir)
            return info

        info = DeploymentInfo(
            session_id=session_id,
            status="running",
            url=url,
            port=port,
            pid=pid,
            log_path=str(log_path),
            started_at=time.time(),
        )
        self._deployments[session_id] = info
        self._persist(session_id, info, project_dir)

        logger.info(
            f"[{session_id}] Deployer: LIVE at {url} (pid={pid}, port={port})"
        )
        return info

    def get_deployment(self, session_id: str) -> Optional[DeploymentInfo]:
        info = self._deployments.get(session_id)
        if info is None:
            return None
        # Refresh status from PID liveness
        if info.pid and not self._pid_alive(info.pid) and info.status == "running":
            info.status = "stopped"
        return info

    def stop_deployment(self, session_id: str) -> bool:
        info = self._deployments.get(session_id)
        if info is None or info.pid is None:
            return False
        try:
            os.kill(info.pid, 15)  # SIGTERM
            time.sleep(0.5)
            if self._pid_alive(info.pid):
                os.kill(info.pid, 9)  # SIGKILL
        except ProcessLookupError:
            pass
        info.status = "stopped"
        return True

    def list_deployments(self) -> list[DeploymentInfo]:
        return list(self._deployments.values())

    # ── Internals ──────────────────────────────────────────────────────────────

    def _unzip(self, session_id: str, zip_path: Path) -> Path:
        target = DEPLOY_BASE / session_id
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(target)
        logger.info(f"[{session_id}] Deployer: unzipped to {target}")
        return target

    def _create_venv_and_install(self, project_dir: Path) -> None:
        venv_dir = project_dir / ".venv"
        # Create venv
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"venv creation failed: {result.stderr}")

        pip_bin = venv_dir / "bin" / "pip"
        if not pip_bin.exists():
            pip_bin = venv_dir / "Scripts" / "pip.exe"  # Windows fallback

        req_file = project_dir / "requirements.txt"
        if not req_file.exists():
            raise RuntimeError("requirements.txt missing in project")

        # Quiet install for cleaner logs
        result = subprocess.run(
            [str(pip_bin), "install", "-q", "-r", str(req_file)],
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"pip install failed (exit {result.returncode}): "
                f"{result.stderr[:500]}"
            )

    def _start_uvicorn(
        self,
        project_dir: Path,
        port: int,
        session_id: str,
    ) -> tuple[int, Path]:
        venv_dir = project_dir / ".venv"
        uvicorn_bin = venv_dir / "bin" / "uvicorn"
        if not uvicorn_bin.exists():
            uvicorn_bin = venv_dir / "Scripts" / "uvicorn.exe"

        backend_dir = project_dir / "backend"
        if not backend_dir.exists():
            raise RuntimeError("backend/ directory missing in project")
        if not (backend_dir / "main.py").exists():
            raise RuntimeError("backend/main.py missing in project")

        log_path = project_dir / "server.log"
        log_fh = open(log_path, "w", encoding="utf-8")

        # Detach from parent's lifecycle — start_new_session=True puts it in
        # its own process group so SIGINT to pipeline_engine doesn't kill it.
        proc = subprocess.Popen(
            [
                str(uvicorn_bin),
                "main:app",
                "--host", "0.0.0.0",
                "--port", str(port),
            ],
            cwd=str(backend_dir),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        logger.info(
            f"[{session_id}] Deployer: uvicorn pid={proc.pid} on port {port}, "
            f"logs={log_path}"
        )
        return proc.pid, log_path

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but no permission — still alive

    def _persist(
        self,
        session_id: str,
        info: DeploymentInfo,
        project_dir: Path,
    ) -> None:
        """Write deploy.json into project dir for restart-resilience."""
        try:
            (project_dir / "deploy.json").write_text(
                json.dumps(info.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[{session_id}] Could not persist deploy.json: {e}")

    def _reload_from_disk(self) -> None:
        if not DEPLOY_BASE.exists():
            return
        for child in DEPLOY_BASE.iterdir():
            if not child.is_dir():
                continue
            deploy_file = child / "deploy.json"
            if not deploy_file.exists():
                continue
            try:
                data = json.loads(deploy_file.read_text(encoding="utf-8"))
                info = DeploymentInfo(**data)
                # Mark as stopped if pid not alive
                if info.pid and not self._pid_alive(info.pid):
                    info.status = "stopped"
                self._deployments[info.session_id] = info
            except Exception as e:
                logger.warning(f"Could not reload deploy state from {deploy_file}: {e}")

    def _fail(self, session_id: str, error: str) -> DeploymentInfo:
        logger.error(f"[{session_id}] Deployer FAIL: {error}")
        info = DeploymentInfo(
            session_id=session_id,
            status="failed",
            url="",
            port=0,
            error=error,
            started_at=time.time(),
        )
        self._deployments[session_id] = info
        return info
