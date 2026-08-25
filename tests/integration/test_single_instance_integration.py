"""单实例的真实进程验证（spec: single-instance）。

以子进程运行驻留探针、以 taskkill /F 模拟强杀，覆盖任务 1.4 / 1.7 / 1.9：
- 强杀（无任何清理路径）后连续 5 次重启均能启动——陈旧端点不得演变为
  永久性故障（design D3 的核心风险）；
- 不同端点名（对应不同目录副本）可同时驻留；
- 正常退出（走 shutdown）后端点可被新实例复用。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
_PROBE = Path(__file__).parent / "_residency_probe.py"


def _launch(name: str, workdir: Path) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(_SRC)}
    return subprocess.Popen(
        [sys.executable, str(_PROBE), name, str(workdir)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_file(path: Path, timeout_s: float = 30.0) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            return path.read_text(encoding="utf-8")
        time.sleep(0.1)
    raise TimeoutError(f"等待文件超时：{path}")


def _kill_hard(proc: subprocess.Popen) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
        check=True,
        capture_output=True,
    )
    proc.wait(timeout=10)


def _stop_gracefully(workdir: Path, proc: subprocess.Popen) -> None:
    (workdir / "stop.txt").write_text("1", encoding="utf-8")
    proc.wait(timeout=15)


def test_强杀后连续五次重启均能正常启动(tmp_path):
    name = "ocrtool-it-kill-loop"
    for round_no in range(5):
        workdir = tmp_path / f"round-{round_no}"
        proc = _launch(name, workdir)
        try:
            outcome = _wait_for_file(workdir / "outcome.txt")
            assert outcome == "first_instance", f"第 {round_no + 1} 轮启动被判为 {outcome}"
            _wait_for_file(workdir / "ready.txt")
        finally:
            _kill_hard(proc)


def test_重复启动请求激活且自身不驻留(tmp_path):
    name = "ocrtool-it-activate"
    first_dir = tmp_path / "first"
    proc = _launch(name, first_dir)
    try:
        assert _wait_for_file(first_dir / "outcome.txt") == "first_instance"
        _wait_for_file(first_dir / "ready.txt")

        second_dir = tmp_path / "second"
        second = _launch(name, second_dir)
        # 第二实例传达激活意图后立即退出（不产生常驻进程）
        returncode = second.wait(timeout=30)
        assert returncode == 0
        assert _wait_for_file(second_dir / "outcome.txt") == "already_running"
        # 已有实例收到激活请求
        _wait_for_file(first_dir / "activated.txt")
    finally:
        _stop_gracefully(first_dir, proc)


def test_不同端点名的两个实例可同时驻留(tmp_path):
    # 对应 design D4：不同目录的两份便携副本（端点名不同）互不视为重复启动
    dirs = {}
    procs = []
    try:
        for label in ("copy-a", "copy-b"):
            workdir = tmp_path / label
            proc = _launch(f"ocrtool-it-{label}", workdir)
            procs.append(proc)
            assert _wait_for_file(workdir / "outcome.txt") == "first_instance"
            _wait_for_file(workdir / "ready.txt")
            dirs[label] = workdir
    finally:
        for workdir in dirs.values():
            (workdir / "stop.txt").write_text("1", encoding="utf-8")
        for proc in procs:
            proc.wait(timeout=15)


def test_正常退出后端点可被新实例复用(tmp_path):
    name = "ocrtool-it-release"
    first_dir = tmp_path / "first"
    first = _launch(name, first_dir)
    _wait_for_file(first_dir / "ready.txt")
    _stop_gracefully(first_dir, first)

    second_dir = tmp_path / "second"
    second = _launch(name, second_dir)
    try:
        assert _wait_for_file(second_dir / "outcome.txt") == "first_instance"
        _wait_for_file(second_dir / "ready.txt")
    finally:
        _stop_gracefully(second_dir, second)
