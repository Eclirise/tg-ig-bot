from __future__ import annotations

from pathlib import Path

import pytest

import app.services.maintenance_service as maintenance_module
from app.services.maintenance_service import MaintenanceService


class StubProcess:
    def __init__(self, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


@pytest.mark.asyncio()
async def test_update_downloader_tools_success(config_factory, monkeypatch, tmp_path: Path) -> None:
    config = config_factory()
    script_dir = config.project_dir / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "oracle_centos7_manager.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    async def fake_exec(*args, **kwargs):
        return StubProcess(0, b"download tools updated\nInstaloader: 4.14\n", b"")

    monkeypatch.setattr(maintenance_module, "which", lambda name: "/bin/bash")
    monkeypatch.setattr(maintenance_module.asyncio, "create_subprocess_exec", fake_exec)

    service = MaintenanceService(config)
    result = await service.update_downloader_tools()

    assert result.returncode == 0
    assert "download tools updated" in result.render_message()


@pytest.mark.asyncio()
async def test_update_downloader_tools_failure_raises(config_factory, monkeypatch) -> None:
    config = config_factory()
    script_dir = config.project_dir / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "oracle_centos7_manager.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    async def fake_exec(*args, **kwargs):
        return StubProcess(2, b"", b"pip check failed\n")

    monkeypatch.setattr(maintenance_module, "which", lambda name: "/bin/bash")
    monkeypatch.setattr(maintenance_module.asyncio, "create_subprocess_exec", fake_exec)

    service = MaintenanceService(config)

    with pytest.raises(RuntimeError, match="退出码 2"):
        await service.update_downloader_tools()