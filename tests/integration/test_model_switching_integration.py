"""model-switching 集成测试：真实引擎切换、关闭退出、删除回退、反复切换释放。

依赖本地模型（scripts/fetch_models.ps1 落地 small 与 tiny）；无模型时跳过。
"""

from __future__ import annotations

import gc
import sys
import weakref
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_helpers import process_events_until

from ocrtool.app import paths
from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.ocr import model_manager
from ocrtool.ocr.service import OCRService, default_engine_factory
from ocrtool.utils import logger as logger_mod

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"
SAMPLES_DIR = PROJECT_ROOT / "tests" / "samples"

requires_local_models = pytest.mark.skipif(
    not (MODELS_ROOT / "ppocrv6-small" / "det.onnx").exists()
    or not (MODELS_ROOT / "ppocrv6-tiny" / "det.onnx").exists(),
    reason="本地模型未完整落地（运行 scripts/fetch_models.ps1 后重试）",
)


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


def _find(models_root: Path, model_id: str):
    for info in model_manager.available_models(models_root):
        if info.model_id == model_id:
            return info
    raise AssertionError(f"模型未找到：{model_id}")


@requires_local_models
class TestRealSwitching:
    def test_真实引擎切换后识别走新模型(self):
        small = _find(MODELS_ROOT, "ppocrv6-small")
        tiny = _find(MODELS_ROOT, "ppocrv6-tiny")
        sample = _load_sample("english.png")

        service = OCRService(small)
        first = service.recognize(sample)
        assert first.model_name == "PP-OCRv6 Small"

        service.switch_model(tiny)
        second = service.recognize(sample)
        assert second.model_name == "PP-OCRv6 Tiny"
        assert second.text, "Tiny 模型对英文样本必须产出文本"

    def test_反复切换20次_旧引擎全部释放内存回落(self):
        """3.4：每次切换后旧引擎被释放——引擎对象层面无累积驻留。

        进程 RSS 受 onnxruntime 内存池归还策略影响只作参考不作断言；
        Python 侧「任意时刻至多一个引擎存活」是内存回落的必要条件与
        可靠观测点。
        """
        small = _find(MODELS_ROOT, "ppocrv6-small")
        tiny = _find(MODELS_ROOT, "ppocrv6-tiny")
        sample = _load_sample("english.png")
        refs: list[weakref.ref] = []

        def tracking_factory(params):
            engine = default_engine_factory(params)
            refs.append(weakref.ref(engine))
            return engine

        service = OCRService(small, engine_factory=tracking_factory)
        service.recognize(sample)
        for round_no in range(20):
            target = tiny if round_no % 2 == 0 else small
            service.switch_model(target)
            result = service.recognize(sample)
            assert result.model_name == target.name, "切换后识别必须走新模型"

        gc.collect()
        alive = [r for r in refs if r() is not None]
        assert len(alive) <= 1, f"20 次切换后仍存活 {len(alive)} 个引擎，存在释放泄漏"

    def test_损坏目标模型文件后切换_回滚且识别可用(self):
        """2.2 真实文件版：det.onnx 被截断 → 加载失败 → 原模型继续工作。"""
        import shutil
        import tempfile

        small = _find(MODELS_ROOT, "ppocrv6-small")
        sample = _load_sample("english.png")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(MODELS_ROOT / "ppocrv6-tiny", root / "ppocrv6-tiny")
            # 截断 det.onnx 制造「文件存在但内容损坏」
            det = root / "ppocrv6-tiny" / "det.onnx"
            det.write_bytes(det.read_bytes()[:64])
            tiny_broken = _find(root, "ppocrv6-tiny")

            service = OCRService(small)
            service.recognize(sample)
            from ocrtool.ocr.exceptions import ModelLoadError

            with pytest.raises(ModelLoadError) as exc_info:
                service.switch_model(tiny_broken)
            assert "仍在使用原模型" in str(exc_info.value)
            # 功能不中断：原模型继续识别
            after = service.recognize(sample)
            assert after.model_name == "PP-OCRv6 Small"
            assert after.text


@requires_local_models
class TestDeletedModelFallback:
    def test_配置记录的模型被删除后回退到推荐模型并记日志(self, caplog):
        """3.3：回退决策点在 resolve_model（启动路径唯一入口）。"""
        with caplog.at_level("ERROR", logger="ocrtool.ocr"):
            resolved = model_manager.resolve_model(MODELS_ROOT, "ppocrv6-deleted")
        assert resolved is not None
        assert resolved.model_id == "ppocrv6-small", "必须回退到 recommended 模型"
        assert any("ppocrv6-deleted" in r.message for r in caplog.records)


@requires_local_models
class TestCloseDuringSwitch:
    def test_切换进行中关闭程序可正常退出(self, qapp, tmp_path, monkeypatch):
        """2.5：真实模型加载中关窗——不挂起、不崩溃，事件循环照常运转。

        真实引擎加载耗时数百毫秒，足以覆盖「加载中关窗」窗口期。
        """
        from ocrtool.ui.main_window import MainWindow

        small = _find(MODELS_ROOT, "ppocrv6-small")
        tiny = _find(MODELS_ROOT, "ppocrv6-tiny")

        class ConfigStub:
            def __init__(self) -> None:
                self.saved: list[dict] = []

            def get(self, key, default=None):
                return {"ocr.model": "ppocrv6-small", "ocr.max_edge_px": 6000,
                        "ui.auto_copy": False, "ui.show_boxes": False}.get(key, default)

            def set(self, key, value) -> None:
                pass

            def save(self) -> None:
                self.saved.append({})

        # 先用 small 识别一次使引擎已加载，再切换到 tiny（触发真实加载）
        service = OCRService(small)
        service.recognize(_load_sample("english.png"))
        controller = OcrController(service)
        monkeypatch.setattr(
            "ocrtool.ui.main_window.QMessageBox.warning",
            staticmethod(lambda *a, **k: None),
        )
        window = MainWindow(controller, ConfigStub(), startup_warnings=[])
        window.show()

        assert controller.switch_model(tiny) is True
        assert window.close() is True, "切换进行中关窗不得被阻塞"

        # 事件循环继续运转直至切换在后台完成——无异常即未崩溃
        process_events_until(qapp, lambda: not controller.busy, timeout_s=30)
        assert controller.state.name == "IDLE"
