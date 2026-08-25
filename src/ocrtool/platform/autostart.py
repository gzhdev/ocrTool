"""开机自启动（spec: auto-start）——当前用户的登录启动项。

- 只写 HKCU Run 键（当前用户位置），MUST NOT 请求提权、不写系统级
  位置（spec: auto-start）；
- 登录以托盘模式拉起：命令行带 `--tray`（application 的显示决策消费），
  路径以引号包裹，含空格目录安全（spec: auto-start 路径含空格）；
- 路径自愈（design D8）：便携目录就是会被移动。每次启动时若功能处于
  开启状态，用当前实际路径重写启动项；路径未变化不产生多余写入；
  关闭状态 MUST NOT 写入。

这是程序第一处在自身目录之外的持久化痕迹（design D9）——位于
`HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`，删除程序目录
后遗留项无法被自动清理（程序已不存在），该条目指向不存在的文件，系统
会忽略，无实际危害。
"""

from __future__ import annotations

import logging
import re
import sys
import winreg
from pathlib import Path

logger = logging.getLogger("ocrtool.platform")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "OCRTool"
TRAY_ARG = "--tray"


class AutoStartError(RuntimeError):
    """登录启动项写入/移除失败，携带用户可读说明。"""


def launch_command() -> str:
    """当前程序的自启命令（引号包裹路径 + --tray）。"""
    if getattr(sys, "frozen", False):
        target = sys.executable
    else:
        import ocrtool

        target = str(Path(ocrtool.__file__).parent / "main.py")
        return f'"{sys.executable}" "{target}" {TRAY_ARG}'
    return f'"{target}" {TRAY_ARG}'


def read_command(value_name: str = VALUE_NAME) -> str | None:
    """读取登录启动项当前值；未设置返回 None（即功能处于关闭状态）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return str(value)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AutoStartError(f"读取登录启动项失败：{exc}") from exc


def is_enabled(value_name: str = VALUE_NAME) -> bool:
    try:
        return read_command(value_name) is not None
    except AutoStartError:
        return False  # 状态不可知时按未生效呈现，不得虚报已开启


def enable(value_name: str = VALUE_NAME) -> None:
    """写入当前用户的登录启动项，指向当前程序。失败抛 AutoStartError。"""
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, launch_command())
        logger.info("已开启开机启动（HKCU Run，值名=%s）", value_name)
    except OSError as exc:
        raise AutoStartError(f"写入登录启动项失败：{exc}") from exc


def disable(value_name: str = VALUE_NAME) -> None:
    """移除登录启动项；未设置视为已达成目标（幂等）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, value_name)
        logger.info("已关闭开机启动（值名=%s）", value_name)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise AutoStartError(f"移除登录启动项失败：{exc}") from exc


def _command_paths(command: str) -> list[str]:
    """提取命令中的路径 token（跳过 -- 参数），规范化（resolve+小写）。"""
    paths = []
    for quoted, bare in re.findall(r'"([^"]*)"|(\S+)', command):
        token = quoted or bare
        if token.startswith("-"):
            continue
        candidate = Path(token)
        if candidate.is_absolute():
            paths.append(str(candidate.resolve()).casefold())
        else:
            paths.append(token.casefold())
    return paths


def heal(value_name: str = VALUE_NAME) -> bool:
    """路径自愈：开启状态下用当前实际路径重写启动项。

    返回是否发生了写入——路径未变化 MUST NOT 产生多余写入（spec:
    auto-start）；关闭状态（无值）MUST NOT 写入。
    """
    try:
        current = read_command(value_name)
    except AutoStartError:
        logger.exception("登录启动项状态读取失败，跳过本次自愈")
        return False
    if current is None:
        return False  # 关闭状态
    desired = launch_command()
    if _command_paths(current) == _command_paths(desired):
        return False
    try:
        enable(value_name)
    except AutoStartError:
        logger.exception("登录启动项自愈写入失败")
        return False
    logger.info("登录启动项路径已自愈：旧命令指向位置与当前程序不同")
    return True
