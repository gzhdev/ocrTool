"""app-logging 隐私集成测试：执行真实识别后，识别文本不落日志、不上标准输出。

依赖本地模型（先运行 scripts/fetch_models.ps1 或手工放置）；
无模型环境下跳过，不视为失败。
"""

import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from ocrtool.app import paths
from ocrtool.utils import logger as logger_mod

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = PROJECT_ROOT / "models" / "ppocrv6-small"

requires_local_models = pytest.mark.skipif(
    not (MODEL_DIR / "det.onnx").exists() or not (MODEL_DIR / "rec.onnx").exists(),
    reason="本地模型未落地（运行 scripts/fetch_models.ps1 后重试）",
)

RECOGNIZED_MARKER = "HELLO OCR 123456"


def _make_test_image() -> np.ndarray:
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    img = Image.new("RGB", (720, 240), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 50), RECOGNIZED_MARKER, fill="black", font=font)
    draw.text((40, 140), "OCRTool Privacy Test", fill="black", font=font)
    return np.asarray(img)[..., ::-1].copy()  # RGB -> BGR


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    target = tmp_path / "user-root"
    target.mkdir()
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(target))
    paths.initialize()
    yield target
    paths.reset_for_tests()
    for handler in logger_mod.get_logger().handlers[:]:
        logger_mod.get_logger().removeHandler(handler)
        handler.close()


def _read_log() -> str:
    for handler in logger_mod.get_logger().handlers:
        handler.flush()
    return (paths.log_dir() / "ocrtool.log").read_text(encoding="utf-8")


@requires_local_models
def test_recognition_text_never_logged_or_printed(capsys):
    """4.3 + 4.4：DEBUG 级别下真实识别，日志只含尺寸/行数/耗时。"""
    from rapidocr import RapidOCR

    logger_mod.setup_logging(level="DEBUG")
    engine = RapidOCR(
        params={
            "Det.model_path": str(MODEL_DIR / "det.onnx"),
            "Rec.model_path": str(MODEL_DIR / "rec.onnx"),
            "Global.use_cls": False,
        }
    )
    logger_mod.silence_third_party_loggers()  # 引擎初始化可能重新挂载其 handler

    image = _make_test_image()
    start = time.perf_counter()
    result = engine(image)
    elapsed_ms = (time.perf_counter() - start) * 1000

    txts = list(result.txts) if result is not None and result.txts else []
    assert any(RECOGNIZED_MARKER in t for t in txts), "识别未成功，测试前提不成立"

    h, w = image.shape[:2]
    logger_mod.log_recognition_summary(
        width=w, height=h, lines=len(txts), elapsed_ms=elapsed_ms
    )

    log_content = _read_log()
    captured = capsys.readouterr()

    # 隐私红线：识别文本不得出现在日志文件与标准输出/错误
    for stream_name, stream in (("日志", log_content), ("stdout", captured.out), ("stderr", captured.err)):
        assert RECOGNIZED_MARKER not in stream, f"识别文本泄漏到{stream_name}"
        assert "OCRTool Privacy Test" not in stream, f"识别文本泄漏到{stream_name}"

    # 摘要按许可格式记录了尺寸、行数、耗时
    assert f"尺寸={w}x{h}" in log_content
    assert f"行数={len(txts)}" in log_content
    assert "耗时=" in log_content
