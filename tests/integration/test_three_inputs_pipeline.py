"""image-input 集成测试（任务 3.6）：三种输入方式载入并识别，全程无临时文件。

依赖本地模型与测试样本；缺失环境跳过。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_helpers import process_events_until

from ocrtool.app import application, paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"
SAMPLES_DIR = PROJECT_ROOT / "tests" / "samples"

requires_local_models = pytest.mark.skipif(
    not (MODELS_ROOT / "ppocrv6-small" / "det.onnx").exists(),
    reason="本地模型未落地",
)
requires_samples = pytest.mark.skipif(
    not (SAMPLES_DIR / "mixed.png").exists(), reason="测试样本未生成"
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


@pytest.fixture
def app_window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))
    service, controller, config, warnings = application.bootstrap()
    window = application.create_main_window(controller, config, warnings)
    window.resize(800, 600)
    window.show()
    yield window
    paths.reset_for_tests()


def _snapshot_images() -> set[Path]:
    """可写状态根与系统临时目录下的全部图像文件快照。"""
    found: set[Path] = set()
    roots = [paths.user_root(), Path(tempfile.gettempdir())]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                found.add(path)
    return found


def _recognize_and_wait(qapp, window) -> None:
    window.start_recognition()
    process_events_until(qapp, lambda: not window._controller.busy, timeout_s=60)


@requires_local_models
@requires_samples
def test_三种输入方式载入并识别且无临时文件(qapp, app_window):
    window = app_window
    before = _snapshot_images()

    # 1. 文件路径载入（文件选择对话框的最终产物就是路径）
    window.load_from_path(SAMPLES_DIR / "mixed.png")
    assert window._viewer.has_image()
    _recognize_and_wait(qapp, window)
    assert "OCRTool" in window._result_panel.text or "中英文" in window._result_panel.text
    first_text = window._result_panel.text

    # 2. 剪贴板载入
    import io

    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    with Image.open(SAMPLES_DIR / "english.png") as pil:
        buf = io.BytesIO()
        pil.convert("RGB").save(buf, format="png")
    qimage = QImage()
    qimage.loadFromData(buf.getvalue())
    QApplication.clipboard().setImage(qimage)

    window.load_from_clipboard()
    assert window._viewer.has_image()
    _recognize_and_wait(qapp, window)
    assert "fox" in window._result_panel.text
    assert window._result_panel.text != first_text

    # 3. 拖放载入（dropEvent 的最终产物也是路径——走同一入口，此处验证管线）
    window.load_from_path(SAMPLES_DIR / "chinese.png")
    _recognize_and_wait(qapp, window)
    assert "中文" in window._result_panel.text or "第二行" in window._result_panel.text

    # 全程识别后：磁盘上未产生任何临时图像文件（spec: image-input）
    after = _snapshot_images()
    assert after == before, f"识别过程产生了临时文件：{sorted(after - before)}"
