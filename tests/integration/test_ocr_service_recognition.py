"""ocr-engine 服务层集成测试：断网识别、空样本结果契约与隐私边界。

依赖本地模型（scripts/fetch_models.ps1 落地）；无模型环境下跳过。
以「死代理」模拟断网——服务层显式传本地模型路径，任何下载尝试都会
立刻失败；识别仍成功即证明链路对网络零依赖（spec: ocr-engine）。
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from ocrtool.app import paths
from ocrtool.config import manager as config_manager_mod
from ocrtool.ocr import model_manager
from ocrtool.ocr.service import OCRService
from ocrtool.utils import logger as logger_mod

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"
SAMPLES_DIR = PROJECT_ROOT / "tests" / "samples"

requires_local_models = pytest.mark.skipif(
    not (MODELS_ROOT / "ppocrv6-small" / "det.onnx").exists(),
    reason="本地模型未落地（运行 scripts/fetch_models.ps1 后重试）",
)

requires_samples = pytest.mark.skipif(
    not (SAMPLES_DIR / "no_text.png").exists(),
    reason="测试样本未生成（运行 tests/samples/generate_samples.py）",
)

DEAD_PROXY = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def _dead_network(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(var, DEAD_PROXY)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    target = tmp_path / "user-root"
    target.mkdir()
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(target))
    paths.initialize()
    logger_mod.setup_logging()
    yield target
    paths.reset_for_tests()
    for handler in logger_mod.get_logger().handlers[:]:
        logger_mod.get_logger().removeHandler(handler)
        handler.close()


def _load_sample(name: str) -> np.ndarray:
    with Image.open(SAMPLES_DIR / name) as img:
        return np.asarray(img.convert("RGB"))[..., ::-1].copy()


def _make_service() -> OCRService:
    config = config_manager_mod.load_config()
    model = model_manager.resolve_model(MODELS_ROOT, config.get("ocr.model"))
    assert model is not None, "本地模型应可解析"
    return OCRService(model, cpu_threads=int(config.get("runtime.cpu_threads", 4)))


def _read_log() -> str:
    for handler in logger_mod.get_logger().handlers:
        handler.flush()
    return (paths.log_dir() / "ocrtool.log").read_text(encoding="utf-8")


@requires_local_models
@requires_samples
def test_断网环境下识别成功():
    """死代理下端到端成功：证明服务层链路零网络依赖（任务 1.4 验证）。"""
    service = _make_service()
    result = service.recognize(_load_sample("mixed.png"))
    assert result.line_count >= 1
    assert "OCRTool" in result.text or "中英文" in result.text


@requires_local_models
@requires_samples
def test_无文字样本得到空结果而非异常():
    """识别成功但零文本：text 为空串、lines 为空集合、不抛错（任务 1.9）。"""
    service = _make_service()
    result = service.recognize(_load_sample("no_text.png"))

    assert result.text == ""
    assert result.lines == ()
    assert result.line_count == 0
    assert result.elapsed_ms > 0


@requires_local_models
@requires_samples
def test_识别文本不出现在日志与标准输出(capsys):
    """第三方组件输出被抑制：日志文件与 stdio 均无识别文本（任务 1.5 验证）。"""
    service = _make_service()
    result = service.recognize(_load_sample("mixed.png"))
    assert result.text, "样本应识别出文本（否则断言无意义）"

    log_text = _read_log()
    captured = capsys.readouterr()
    for leaked in (result.text, result.lines[0].text):
        first_line = leaked.splitlines()[0]
        assert first_line not in log_text, f"识别文本泄漏进日志：{first_line!r}"
        assert first_line not in captured.out + captured.err


@requires_local_models
@requires_samples
def test_DEBUG级别下识别文本依然不落日志(monkeypatch, tmp_path):
    """隐私回归（任务 5.3）：DEBUG 级别的约束与 INFO 一致（spec: app-logging）。"""
    target = tmp_path / "debug-root"
    target.mkdir()
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(target))
    paths.initialize()
    logger_mod.setup_logging(level="DEBUG")

    service = _make_service()
    result = service.recognize(_load_sample("mixed.png"))
    assert result.text

    log_text = _read_log()
    assert "DEBUG" in log_text, "DEBUG 级别应产生 DEBUG 日志（否则未真正生效）"
    first_line = result.text.splitlines()[0]
    assert first_line not in log_text, f"DEBUG 级别泄漏识别文本：{first_line!r}"

    paths.reset_for_tests()
    for handler in logger_mod.get_logger().handlers[:]:
        logger_mod.get_logger().removeHandler(handler)
        handler.close()
