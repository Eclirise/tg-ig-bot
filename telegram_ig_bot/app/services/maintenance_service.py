from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from shutil import which

from app.config import AppConfig


def _tail_lines(text: str, *, limit: int = 12) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-limit:])


@dataclass(slots=True)
class ToolUpdateResult:
    returncode: int
    stdout: str
    stderr: str

    def render_message(self) -> str:
        body = _tail_lines(self.stdout)
        if self.stderr.strip():
            body = "\n\n".join(part for part in [body, "stderr:\n" + _tail_lines(self.stderr, limit=8)] if part)
        if not body:
            body = "更新完成，但脚本没有返回详细输出。"
        return "下载工具更新完成。\n\n" + body

    def render_error(self) -> str:
        body = _tail_lines(self.stderr) or _tail_lines(self.stdout) or "脚本没有返回更多错误信息。"
        return f"命令执行失败，退出码 {self.returncode}。\n\n{body}"


class MaintenanceService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(__name__)

    @property
    def script_path(self) -> Path:
        return self.config.project_dir / "scripts" / "oracle_centos7_manager.sh"

    async def update_downloader_tools(self) -> ToolUpdateResult:
        script_path = self.script_path
        if not script_path.exists():
            raise RuntimeError(f"未找到运维脚本：{script_path}")
        bash_bin = which("bash")
        if not bash_bin:
            raise RuntimeError("当前系统未找到 bash，无法执行更新脚本。")
        process = await asyncio.create_subprocess_exec(
            bash_bin,
            str(script_path),
            "update-tools",
            cwd=str(self.config.project_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        result = ToolUpdateResult(
            returncode=process.returncode,
            stdout=stdout.decode("utf-8", errors="ignore"),
            stderr=stderr.decode("utf-8", errors="ignore"),
        )
        if process.returncode != 0:
            raise RuntimeError(result.render_error())
        return result

    async def restart_application(self, *, delay_seconds: float = 2.0) -> None:
        await asyncio.sleep(max(0.2, delay_seconds))
        self.logger.warning("收到管理员重启指令，进程即将退出，等待 systemd 自动拉起。")
        os._exit(0)
