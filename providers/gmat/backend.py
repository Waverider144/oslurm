from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendInfo:
    mode: str
    executable: str | None = None
    version: str = "unknown"
    real: bool = False
    reason: str = ""


def detect_backend() -> BackendInfo:
    root = Path(__file__).resolve().parents[2]
    fixed_root = root / "third_party" / "GMAT-R2026a-fixed"
    gmat_root = fixed_root if fixed_root.exists() else root / "third_party" / "GMAT-R2026a"
    if importlib.util.find_spec("gmat") or importlib.util.find_spec("GMAT"):
        return BackendInfo(mode="python-api", real=True)
    exe = (
        shutil.which("GmatConsole")
        or shutil.which("GMAT")
        or (str(gmat_root / "bin" / "GmatConsole") if (gmat_root / "bin" / "GmatConsole").exists() else None)
        or (str(gmat_root / "bin" / "GMAT") if (gmat_root / "bin" / "GMAT").exists() else None)
    )
    if exe:
        version = "unknown"
        try:
            result = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
            text = (result.stdout or result.stderr).strip()
            if "Build Date:" in text:
                version = "R2026a"
            elif text:
                version = text.splitlines()[0]
        except Exception:
            pass
        try:
            smoke = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10, cwd=str(Path(exe).parent))
            text = smoke.stdout + smoke.stderr
            if smoke.returncode == 0:
                return BackendInfo(mode="subprocess", executable=exe, version=version, real=True)
            return BackendInfo(
                mode="subprocess-unusable",
                executable=exe,
                version=version,
                real=False,
                reason=f"GMAT executable was found but smoke test exited {smoke.returncode}: {text.strip().splitlines()[-1] if text.strip() else 'no output'}",
            )
        except Exception as exc:  # noqa: BLE001
            return BackendInfo(mode="subprocess-unusable", executable=exe, version=version, real=False, reason=str(exc))
    return BackendInfo(mode="mock", real=False, reason="GMAT Python API and console executable were not found")


def write_subprocess_script(_scenario: Path, _workdir: Path) -> Path:
    raise NotImplementedError("Real GMAT subprocess script generation is not available without GMAT installed")
