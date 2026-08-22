"""任务 4.8 / 4.9：应用组装不加载模型；界面模块不引入被禁组件。"""

from __future__ import annotations

import re
from pathlib import Path

UI_MODULES = sorted(Path("src/ocrtool/ui").rglob("*.py")) + [
    Path("src/ocrtool/app/application.py")
]


def test_ui_模块无被禁组件导入():
    """spec: main-window「界面构成不引入被禁组件」——检视全部界面模块源码。"""
    forbidden = re.compile(
        r"(WebEngine|WebChannel|Multimedia|Qml|Quick|Qt3D|Charts)", re.IGNORECASE
    )
    for module in UI_MODULES:
        for lineno, line in enumerate(
            module.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith(("import ", "from ")):
                match = forbidden.search(line)
                assert match is None, (
                    f"{module}:{lineno} 引入被禁组件：{line.strip()}"
                )


def test_bootstrap_组装后模型未加载(qapp, tmp_path, monkeypatch):
    """spec: ocr-engine 惰性加载——启动序列完成时引擎不得存在（权重未进内存）。"""
    monkeypatch.setenv("OCRTOOL_DATA_DIR", str(tmp_path / "user"))
    from ocrtool.app import application, paths

    service, controller, config, warnings = application.bootstrap()

    assert service.engine_loaded is False, "启动阶段不得加载模型"
    assert controller.model_name  # 控制器可用
    assert not controller.busy

    window = application.create_main_window(controller, config, warnings)
    assert window._controller is controller  # 注入而非新建
    assert service.engine_loaded is False, "窗口组装仍不得触发模型加载"
    paths.reset_for_tests()
