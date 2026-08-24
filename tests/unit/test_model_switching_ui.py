"""model-switching 界面测试：选择入口、切换持久化、结果产出模型标注。

覆盖任务 3.1/3.2（切换写配置/失败不写）与 4.1-4.5（菜单展示、当前标示、
旧结果标注保留、重新识别标注更新、识别或切换期间入口禁用）。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_helpers import process_events_until

from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.ocr.exceptions import ModelLoadError
from ocrtool.ocr.result import OcrLine, OcrResult
from ocrtool.ui.main_window import MainWindow


class SwitchableService:
    """可切换假服务：recognize 产出携带当前模型名的结果。"""

    def __init__(self, model_id: str = "id-a", model_name: str = "模型A") -> None:
        self.model_id = model_id
        self.model_name = model_name
        self.engine_loaded = True
        self.switch_calls: list[str] = []
        self.fail_next_recognition = False

    def preload(self) -> None:  # pragma: no cover - 已加载占位
        pass

    def recognize(self, image, *, scale: float = 1.0) -> OcrResult:
        if self.fail_next_recognition:
            self.fail_next_recognition = False
            from ocrtool.ocr.exceptions import RecognitionError

            raise RecognitionError("识别过程发生错误")
        line = OcrLine(text="一行", score=0.9, box=((0, 0), (1, 0), (1, 1), (0, 1)))
        return OcrResult(
            text="一行",
            lines=(line,),
            elapsed_ms=5.0,
            width=8,
            height=6,
            model_name=self.model_name,
        )

    def switch_model(self, model) -> None:
        if getattr(model, "raise_on_switch", None):
            raise model.raise_on_switch
        self.switch_calls.append(model.model_id)
        self.model_id = model.model_id
        self.model_name = model.name


def make_model(model_id: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(model_id=model_id, name=name)


def make_window(qapp, tmp_path, monkeypatch, models, service=None):
    monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))
    from ocrtool.app import paths

    # 菜单扫描走真实目录逻辑，但把模型根指到临时目录以获得完全控制
    (tmp_path / "models").mkdir(exist_ok=True)
    real_app_root = paths.get_app_root
    monkeypatch.setattr(paths, "get_app_root", lambda: tmp_path)
    paths.reset_for_tests()
    paths.initialize()
    for info in models:
        directory = tmp_path / "models" / info.model_id
        directory.mkdir(exist_ok=True)
        description = {
            "id": info.model_id,
            "name": info.name,
            "det_model": "det.onnx",
            "rec_model": "rec.onnx",
            "language_coverage": ["zh"],
            "recommended": False,
        }
        (directory / "model.json").write_text(
            json.dumps(description, ensure_ascii=False), encoding="utf-8"
        )
        (directory / "det.onnx").write_bytes(b"x")
        (directory / "rec.onnx").write_bytes(b"x")

    service = service or SwitchableService()
    controller = OcrController(service)
    config = DottedConfig(
        {
            "ocr": {"model": "id-a", "max_edge_px": 6000},
            "runtime": {"cpu_threads": 4},
            "logging": {"level": "INFO"},
            "ui": {"auto_copy": False, "show_boxes": False},
        }
    )
    # 模态对话框在 offscreen 下仍会阻塞事件循环，测试全程拦截
    monkeypatch.setattr(
        "ocrtool.ui.main_window.QMessageBox.warning",
        staticmethod(lambda *args, **kwargs: None),
    )
    win = MainWindow(controller, config, startup_warnings=[])
    win.resize(900, 600)
    yield win, controller, service, config
    monkeypatch.setattr(paths, "get_app_root", real_app_root)
    paths.reset_for_tests()


class DottedConfig:
    """ConfigManager 点路径替身：get/set/save，save 记录快照供断言。"""

    def __init__(self, values: dict) -> None:
        self._values = copy.deepcopy(values)
        self.snapshots: list[dict] = []

    def get(self, dotted_key: str, default=None):
        node = self._values
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted_key: str, value) -> None:
        parts = dotted_key.split(".")
        node = self._values
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def save(self) -> None:
        self.snapshots.append(copy.deepcopy(self._values))


def image() -> np.ndarray:
    return np.zeros((4, 4, 3), dtype=np.uint8)


def run_recognition(qapp, controller) -> None:
    assert controller.start_recognition(image())
    process_events_until(qapp, lambda: not controller.busy)


def run_switch(qapp, controller, model) -> None:
    assert controller.switch_model(model)
    process_events_until(qapp, lambda: not controller.busy)


class TestModelMenu:
    """4.1：模型选择入口展示全部可用模型并标示当前模型。"""

    def test_菜单列出全部模型并勾选当前(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            win._rebuild_model_menu()
            actions = win._model_menu.actions()
            assert [a.text() for a in actions] == ["模型A", "模型B"]
            assert actions[0].isChecked() is True
            assert actions[1].isChecked() is False

    def test_只有一个模型时不呈现为错误(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            win._rebuild_model_menu()
            actions = win._model_menu.actions()
            assert [a.text() for a in actions] == ["模型A"]
            assert actions[0].isEnabled() is True
            assert actions[0].isChecked() is True

    def test_运行期放入新模型_重新打开菜单即可见(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            win._rebuild_model_menu()
            assert len(win._model_menu.actions()) == 1
            # 运行期放入第二个模型（design D4：无需重启）
            new_dir = tmp_path / "models" / "id-b"
            new_dir.mkdir()
            (new_dir / "model.json").write_text(
                '{"id": "id-b", "name": "模型B", "det_model": "det.onnx",'
                ' "rec_model": "rec.onnx", "language_coverage": ["zh"],'
                ' "recommended": false}',
                encoding="utf-8",
            )
            (new_dir / "det.onnx").write_bytes(b"x")
            (new_dir / "rec.onnx").write_bytes(b"x")
            win._rebuild_model_menu()
            assert [a.text() for a in win._model_menu.actions()] == ["模型A", "模型B"]

    def test_选择当前模型是无操作(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            win._request_model_switch(make_model("id-a", "模型A"))
            assert service.switch_calls == []
            assert controller.switching is False

    def test_菜单重建不累积QActionGroup(self, qapp, tmp_path, monkeypatch):
        """50-1：旧 QActionGroup 必须 deleteLater，重建 20 次后仅存当前一个。

        DeferredDelete 不随 processEvents 派发（仅事件循环运行中处理），
        测试须显式 sendPostedEvents——生产环境 app.exec() 下自然生效。
        """
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtGui import QActionGroup

        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            for _ in range(20):
                win._rebuild_model_menu()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert len(win._model_menu.findChildren(QActionGroup)) == 1


class TestSwitchCompletionState:
    """75-1：切换完成（成功或失败）后状态区文本回落，不残留「正在加载模型…」。

    IDLE-跳过驻留机制是为识别终态（完成/空/失败）设计的；切换路径以
    LOADING 开始以 IDLE 结束，若回调不显式回落，最后写入的是进行时文本
    （spec: ocr-execution「切换完成后恢复：状态回到空闲」）。
    """

    def test_切换成功后状态区回落就绪(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            run_switch(qapp, controller, make_model("id-b", "模型B"))
            assert controller.busy is False
            assert win._status._state_label.text() == "就绪"

    def test_切换失败后状态区回落就绪(self, qapp, tmp_path, monkeypatch):
        failing = make_model("id-b", "模型B")
        failing.raise_on_switch = ModelLoadError("模型切换失败，仍在使用原模型")
        models = [make_model("id-a", "模型A")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            run_switch(qapp, controller, failing)
            assert controller.busy is False
            assert win._status._state_label.text() == "就绪"


class TestSwitchPersistence:
    """3.1/3.2：切换成功写配置；失败保持不变。"""

    def test_切换成功写入用户配置(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            run_switch(qapp, controller, make_model("id-b", "模型B"))
            assert config.get("ocr.model") == "id-b"
            assert config.snapshots, "切换成功必须保存配置"
            assert config.snapshots[-1]["ocr"]["model"] == "id-b"

    def test_切换失败用户配置保持不变(self, qapp, tmp_path, monkeypatch):
        failing = make_model("id-b", "模型B")
        failing.raise_on_switch = ModelLoadError("模型切换失败，仍在使用原模型")
        models = [make_model("id-a", "模型A")]
        service = SwitchableService()
        for win, controller, svc, config in make_window(
            qapp, tmp_path, monkeypatch, models, service=service
        ):
            run_switch(qapp, controller, failing)
            assert config.get("ocr.model") == "id-a"
            assert config.snapshots == []
            assert svc.model_id == "id-a"

    def test_切换失败呈现可读提示且不含技术细节(self, qapp, tmp_path, monkeypatch):
        failing = make_model("id-b", "模型B")
        failing.raise_on_switch = ModelLoadError(
            "模型切换失败，仍在使用原模型", detail="RuntimeError('onnx corrupted')"
        )
        models = [make_model("id-a", "模型A")]
        warnings: list[tuple] = []

        for win, controller, svc, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            # 循环体内覆盖 make_window 的拦截，改为捕获调用参数
            from PySide6.QtWidgets import QMessageBox

            monkeypatch.setattr(
                QMessageBox,
                "warning",
                staticmethod(lambda *args, **kwargs: warnings.append(args)),
            )
            run_switch(qapp, controller, failing)
            assert len(warnings) == 1
            message = warnings[0][-1]
            assert "仍在使用原模型" in message
            assert "onnx corrupted" not in message


class TestResultModelLabel:
    """4.2/4.3/4.4：状态区标明结果的产出模型，切换不误导。"""

    def model_label(self, win) -> str:
        return win._status._model_label.text()

    def test_识别完成标注产出模型(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            run_recognition(qapp, controller)
            assert self.model_label(win) == "模型：模型A"

    def test_切换后旧结果保留且标注仍为旧模型(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            run_recognition(qapp, controller)
            text_before = win._result_panel.text
            run_switch(qapp, controller, make_model("id-b", "模型B"))
            assert self.model_label(win) == "模型：模型A", "旧结果标注不得被新模型覆盖"
            assert win._result_panel.text == text_before, "旧结果文本保持不变"
            # 耗时与行数也属旧结果展示，切换不清（design D5）
            assert win._status._timing_label.text() != "-"

    def test_切换后用新模型重新识别_标注随之更新(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            run_recognition(qapp, controller)
            run_switch(qapp, controller, make_model("id-b", "模型B"))
            assert self.model_label(win) == "模型：模型A"
            run_recognition(qapp, controller)
            assert self.model_label(win) == "模型：模型B"

    def test_无结果时切换_标注跟随当前引擎(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            assert self.model_label(win) == "模型：模型A"
            run_switch(qapp, controller, make_model("id-b", "模型B"))
            assert self.model_label(win) == "模型：模型B"

    def test_清空后标注回到当前引擎模型(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            run_recognition(qapp, controller)
            run_switch(qapp, controller, make_model("id-b", "模型B"))
            assert self.model_label(win) == "模型：模型A"
            win.clear_all()
            assert self.model_label(win) == "模型：模型B"

    def test_识别失败后切换_旧文本与标注均保持旧模型(self, qapp, tmp_path, monkeypatch):
        """75-2：失败路径旧结果保留展示（三代历史行为），其归属标注必须
        同样保留——切换后不得让用户误以为旧文本来自新模型（design D5）。"""
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            run_recognition(qapp, controller)
            assert self.model_label(win) == "模型：模型A"
            # 再次识别失败：旧文本保留展示是既有行为
            service.fail_next_recognition = True
            run_recognition(qapp, controller)
            assert win._result_panel.text == "一行"
            # 切换到 B：旧结果的文本与标注都必须停留
            run_switch(qapp, controller, make_model("id-b", "模型B"))
            assert self.model_label(win) == "模型：模型A"
            assert win._result_panel.text == "一行"
            # 用新模型重新识别成功后标注才更新
            run_recognition(qapp, controller)
            assert self.model_label(win) == "模型：模型B"


class TestEntryAvailability:
    """4.5：识别或切换进行中，模型选择入口不可用。"""

    def test_识别进行中模型入口禁用(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            assert win._model_button.isEnabled() is True
            assert controller.start_recognition(image()) is True
            assert win._model_button.isEnabled() is False
            process_events_until(qapp, lambda c=controller: not c.busy)
            # 再次启动并立即检查：识别启动瞬间入口即禁用
            assert controller.start_recognition(image()) is True
            assert win._model_button.isEnabled() is False
            process_events_until(qapp, lambda c=controller: not c.busy)
            assert win._model_button.isEnabled() is True

    def test_切换进行中模型入口禁用(self, qapp, tmp_path, monkeypatch):
        models = [make_model("id-a", "模型A"), make_model("id-b", "模型B")]
        for win, controller, service, config in make_window(
            qapp, tmp_path, monkeypatch, models
        ):
            assert controller.switch_model(make_model("id-b", "模型B")) is True
            assert win._model_button.isEnabled() is False
            process_events_until(qapp, lambda c=controller: not c.busy)
            assert win._model_button.isEnabled() is True
