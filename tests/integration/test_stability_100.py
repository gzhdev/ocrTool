"""稳定性测试（任务 5.1）：连续 100 次识别。

验证三点（spec: ocr-engine）：
1. 模型加载仅发生一次——以日志中「模型已加载」记录条数为证；
2. 内存无持续上涨——Windows 工作集采样，前后半程均值对比；
3. 界面未卡死——识别全程主线程 10ms 定时器持续触发。

依赖本地模型与样本；缺失环境跳过。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_helpers import process_events_until

from ocrtool.app import application, paths
from ocrtool.utils import logger as logger_mod

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"
SAMPLES_DIR = PROJECT_ROOT / "tests" / "samples"

requires_env = pytest.mark.skipif(
    not (MODELS_ROOT / "ppocrv6-small" / "det.onnx").exists()
    or not (SAMPLES_DIR / "mixed.png").exists(),
    reason="本地模型或测试样本未落地",
)

REPEAT = 100


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def working_set_bytes() -> int:
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.windll.kernel32.GetCurrentProcess(),
        ctypes.byref(counters),
        counters.cb,
    )
    return counters.WorkingSetSize


def _read_log() -> str:
    for handler in logger_mod.get_logger().handlers:
        handler.flush()
    return (paths.log_dir() / "ocrtool.log").read_text(encoding="utf-8")


@requires_env
def test_连续100次识别只加载一次且内存稳定(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))
    service, controller, config, warnings = application.bootstrap()
    window = application.create_main_window(controller, config, warnings)
    window.show()

    ticks: list[int] = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()

    with Image.open(SAMPLES_DIR / "mixed.png") as pil:
        sample = np.asarray(pil.convert("RGB"))[..., ::-1].copy()

    memory_samples: list[int] = []
    for index in range(REPEAT):
        window.load_from_path(SAMPLES_DIR / "mixed.png")
        window.start_recognition()
        process_events_until(qapp, lambda: not controller.busy, timeout_s=60)
        memory_samples.append(working_set_bytes())

    timer.stop()

    # 1. 加载仅一次：日志证据
    log_text = _read_log()
    load_count = log_text.count("模型已加载：")
    assert load_count == 1, f"100 次识别触发了 {load_count} 次模型加载"
    assert service.engine_loaded is True

    # 2. 内存无持续上涨：后半程均值 − 前半程均值应远小于一次模型加载的量级
    half = REPEAT // 2
    early = sum(memory_samples[:half]) / half
    late = sum(memory_samples[half:]) / (REPEAT - half)
    growth_mb = (late - early) / (1024 * 1024)
    assert growth_mb < 30, (
        f"内存持续上涨：前半程均值 {early / 1048576:.1f} MB，"
        f"后半程均值 {late / 1048576:.1f} MB（+{growth_mb:.1f} MB）"
    )

    # 3. 界面未卡死：全程 10ms 定时器持续触发
    assert len(ticks) >= REPEAT * 5, (
        f"识别全程主线程事件处理不足：{len(ticks)} ticks / {REPEAT} 次识别"
    )
    paths.reset_for_tests()
