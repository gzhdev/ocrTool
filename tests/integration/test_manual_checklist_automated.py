"""人工交互清单（设计书 §38.3）中可自动化的项（任务 5.2）。

清单全项：
- 识别时拖动窗口、识别时最小化 —— 真窗口操作，归人工清单；
- 连续识别 —— test_stability_100（100 次）与重入拒绝测试覆盖；
- 无模型启动 —— test_main_window（自检缺失仍启动）覆盖；
- 模型损坏、无效图像、超大图像 —— 本文件与 test_image_input / test_three_inputs_pipeline 覆盖。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_helpers import process_events_until

from ocrtool.app import application, paths
from ocrtool.ocr.exceptions import ModelLoadError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"

requires_local_models = pytest.mark.skipif(
    not (MODELS_ROOT / "ppocrv6-small" / "det.onnx").exists(),
    reason="本地模型未落地",
)


@requires_local_models
def test_模型损坏时识别报加载失败且不崩溃(qapp, tmp_path, monkeypatch):
    """det 文件被替换为垃圾字节：识别路径报告「模型加载失败」，程序保持可用。"""
    import json

    monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))

    broken_root = tmp_path / "models" / "broken-model"
    broken_root.mkdir(parents=True)
    (broken_root / "det.onnx").write_bytes(b"not-an-onnx-model-at-all")
    (broken_root / "rec.onnx").write_bytes(b"not-an-onnx-model-either")
    (broken_root / "model.json").write_text(
        json.dumps(
            {
                "id": "broken",
                "name": "损坏模型",
                "det_model": "det.onnx",
                "rec_model": "rec.onnx",
                "language_coverage": ["ch"],
                "recommended": True,
            }
        ),
        encoding="utf-8",
    )

    from ocrtool.ocr import model_manager
    from ocrtool.ocr.service import OCRService

    resolved = model_manager.resolve_model(tmp_path / "models", None)
    assert resolved is not None and resolved.model_id == "broken"

    service = OCRService(resolved)
    image = b"\x89PNG"  # 任意输入：加载先于识别失败
    with pytest.raises(ModelLoadError) as exc_info:
        service.recognize(__import__("numpy").zeros((4, 4, 3), dtype=__import__("numpy").uint8))
    assert "损坏" in str(exc_info.value) or "加载失败" in str(exc_info.value)
    assert "onnx" not in str(exc_info.value)  # 技术细节不进用户消息
    paths.reset_for_tests()


@requires_local_models
def test_界面层损坏模型走对话框而非崩溃(qapp, tmp_path, monkeypatch):
    """main-window 分级：ModelLoadError → 模态对话框（此处记录调用），程序不退出。"""
    monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))

    dialogs: list[str] = []
    monkeypatch.setattr(
        "ocrtool.ui.main_window.QMessageBox.critical",
        lambda self, title, text: dialogs.append(text),
    )

    service, controller, config, warnings = application.bootstrap()
    window = application.create_main_window(controller, config, warnings)

    from ocrtool.ocr.exceptions import ModelLoadError as MLE

    window._on_error(MLE("模型加载失败，程序可能已损坏，请重新获取"))
    assert dialogs, "模型加载失败必须以对话框呈现"
    paths.reset_for_tests()
