from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def create_temp_dir(root: Path, *, prefix: str = "job-") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=root))


def cleanup_path(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    if path.is_file():
        path.unlink(missing_ok=True)
        return
    shutil.rmtree(path, ignore_errors=True)
