"""路径解析模块——所有文件位置的唯一入口（spec: app-paths）。

双根模型（design D4）：
- APP_ROOT：只读资源根（models / config / resources），= exe 同级（打包）或项目根（开发）；
- USER_ROOT：可写状态根（data / logs / cache），由启动期探测决定：
  OCRTOOL_DATA_DIR 覆盖 → APP_ROOT 实写探针 → %LOCALAPPDATA%\\OCRTool。

必须先于日志系统初始化调用 initialize()，以保证启动期故障可被记录。
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

ENV_DATA_DIR = "OCRTOOL_DATA_DIR"

_USER_DIR_NAMES = ("data", "logs", "cache")


class StorageMode(str, Enum):
    PORTABLE = "Portable"
    INSTALLED = "Installed"
    OVERRIDE = "Override"


class PathResolutionError(RuntimeError):
    """路径解析失败（OCRTOOL_DATA_DIR 无效、全部候选根均不可写等）。"""


@dataclass(frozen=True)
class PathConfig:
    app_root: Path
    user_root: Path
    storage_mode: StorageMode


def get_app_root() -> Path:
    """只读资源根：打包环境为可执行文件所在目录；开发环境为项目根。

    永远基于 sys.executable / __file__ 解析，与当前工作目录无关。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def probe_writable(directory: Path, *, create: bool = False) -> bool:
    """基于真实「创建 + 写入 + 删除」的可写性探针。

    Windows 上 os.access 只反映只读属性、不解析 ACL，对 Program Files 会给出
    假阳性，因此本函数绝不使用权限位查询。无论成败，探测临时文件都会被清理。
    """
    probe_file = directory / f".ocrtool-probe-{uuid.uuid4().hex}"
    try:
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        elif not directory.is_dir():
            return False
        with open(probe_file, "wb") as fh:
            fh.write(b"w")
        return True
    except OSError:
        return False
    finally:
        try:
            probe_file.unlink()
        except OSError:
            pass


def resolve_user_root(
    app_root: Path, env: Mapping[str, str]
) -> tuple[Path, StorageMode]:
    """按既定顺序确定可写状态根。

    环境变量覆盖是用户的显式指令：无效时以明确原因失败，绝不静默回退到
    自动探测结果（否则会出现「指定了目录、数据却写到别处」的困惑）。
    """
    override = (env.get(ENV_DATA_DIR) or "").strip()
    if override:
        target = Path(override).expanduser()
        if not probe_writable(target, create=True):
            raise PathResolutionError(
                f"环境变量 {ENV_DATA_DIR} 指向的目录不可写或无法创建：{target}。"
                f"请修正该环境变量后重新启动。"
            )
        return target, StorageMode.OVERRIDE

    if probe_writable(app_root):
        return app_root, StorageMode.PORTABLE

    local_app_data = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    fallback = Path(local_app_data) / "OCRTool"
    if not probe_writable(fallback, create=True):
        raise PathResolutionError(
            f"程序目录不可写，且回退目录也无法创建或写入：{fallback}。"
            f"请将程序解压到可写位置，或通过环境变量 {ENV_DATA_DIR} 指定数据目录。"
        )
    return fallback, StorageMode.INSTALLED


_state: PathConfig | None = None


def initialize(env: Mapping[str, str] | None = None) -> PathConfig:
    """启动早期调用一次：确定双根与存储模式，并按需创建可写子目录。"""
    global _state
    app_root = get_app_root()
    user_root, mode = resolve_user_root(app_root, os.environ if env is None else env)
    _state = PathConfig(app_root=app_root, user_root=user_root, storage_mode=mode)
    for name in _USER_DIR_NAMES:
        (user_root / name).mkdir(parents=True, exist_ok=True)
    return _state


def _require_state() -> PathConfig:
    if _state is None:
        raise RuntimeError(
            "paths.initialize() 尚未调用——路径解析必须先于其他子系统初始化。"
        )
    return _state


def app_root() -> Path:
    return _require_state().app_root


def user_root() -> Path:
    return _require_state().user_root


def storage_mode() -> StorageMode:
    return _require_state().storage_mode


def model_dir() -> Path:
    return app_root() / "models"


def default_config_path() -> Path:
    return app_root() / "config" / "default.json"


def resource_dir() -> Path:
    return app_root() / "resources"


def data_dir() -> Path:
    return user_root() / "data"


def user_config_path() -> Path:
    return data_dir() / "config.json"


def log_dir() -> Path:
    return user_root() / "logs"


def cache_dir() -> Path:
    return user_root() / "cache"


def reset_for_tests() -> None:
    global _state
    _state = None
