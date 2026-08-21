"""model-assets 禁网集成测试：显式路径识别 + 断网成功 + 缺失模型报本地错误。

以「死代理」模拟断网：任何网络请求都会立刻连接失败。若识别仍成功，
即证明引擎链路对网络零依赖。
"""

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from ocrtool.ocr import model_manager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"

requires_local_models = pytest.mark.skipif(
    not (MODELS_ROOT / "ppocrv6-small" / "det.onnx").exists(),
    reason="本地模型未落地（运行 scripts/fetch_models.ps1 后重试）",
)

DEAD_PROXY = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def _dead_network(monkeypatch):
    """把所有出网流量指向必死端口，任何下载尝试都会立刻失败。"""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(var, DEAD_PROXY)


def _test_image() -> np.ndarray:
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    img = Image.new("RGB", (720, 160), "white")
    ImageDraw.Draw(img).text((40, 50), "OFFLINE 2026", fill="black", font=font)
    return np.asarray(img)[..., ::-1].copy()


@requires_local_models
def test_recognition_offline_with_explicit_paths():
    """断网环境下识别成功，且引擎参数来自 to_engine_params（显式路径+关 cls）。"""
    from rapidocr import RapidOCR

    resolved = model_manager.resolve_model(MODELS_ROOT, "ppocrv6-small")
    assert resolved is not None
    params = resolved.to_engine_params()
    assert params["Global.use_cls"] is False

    engine = RapidOCR(params=params)
    result = engine(_test_image())
    txts = list(result.txts) if result is not None and result.txts else []
    assert any("OFFLINE 2026" in t for t in txts), f"断网识别失败，结果: {txts}"


@requires_local_models
def test_missing_model_reports_local_path_error_not_download():
    """模型缺失时：报本地路径错误（FileNotFoundError 指向本地文件），不发起下载。"""
    from rapidocr import RapidOCR

    resolved = model_manager.resolve_model(MODELS_ROOT, "ppocrv6-small")
    assert resolved is not None
    bad_params = {
        "Det.model_path": str(MODELS_ROOT / "ppocrv6-small" / "不存在.onnx"),
        "Rec.model_path": str(resolved.rec_path),
        "Global.use_cls": False,
    }
    with pytest.raises(FileNotFoundError, match="不存在") as excinfo:
        RapidOCR(params=bad_params)
    # 错误信息指向本地路径，而非任何下载/网络语义
    message = str(excinfo.value)
    assert str(MODELS_ROOT) in message
    for network_hint in ("http", "download", "modelscope", "proxy"):
        assert network_hint not in message.lower()
