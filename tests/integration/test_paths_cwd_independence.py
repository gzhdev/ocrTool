"""app-paths 集成测试：路径解析不依赖当前工作目录（spec: app-paths）。

从与程序目录无关的工作目录（尽量选其他磁盘分区）以子进程启动，
解析结果必须与从程序目录启动时完全一致。
"""

import os
import subprocess
import sys
from pathlib import Path

_RESOLVE_SNIPPET = (
    "from ocrtool.app import paths; "
    "cfg = paths.initialize(); "
    "print(cfg.app_root); print(cfg.user_root); print(cfg.storage_mode.value)"
)


def _pick_foreign_cwd(tmp_path: Path) -> Path:
    """优先选其他磁盘分区的根目录，无其他分区时退到独立临时目录。"""
    system_drive = os.environ.get("SystemDrive", "C:")
    for drive in ("D:\\", "E:\\", "F:\\"):
        if Path(drive).exists() and not drive.startswith(system_drive):
            return Path(drive)
    fallback = tmp_path / "foreign-cwd"
    fallback.mkdir()
    return fallback


def _resolve_from(cwd: Path, data_dir: Path) -> str:
    env = dict(os.environ, **{paths_env(): str(data_dir)})
    result = subprocess.run(
        [sys.executable, "-c", _RESOLVE_SNIPPET],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        check=True,
    )
    return result.stdout


def paths_env() -> str:
    from ocrtool.app.paths import ENV_DATA_DIR

    return ENV_DATA_DIR


def test_resolution_independent_of_cwd(tmp_path):
    data_dir = tmp_path / "data-target"
    data_dir.mkdir()

    from_program_dir = _resolve_from(Path.cwd(), data_dir)
    from_foreign_dir = _resolve_from(_pick_foreign_cwd(tmp_path), data_dir)

    assert from_program_dir == from_foreign_dir
    # 双根均应为绝对路径
    for line in from_program_dir.strip().splitlines()[:2]:
        assert Path(line).is_absolute()
