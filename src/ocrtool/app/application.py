"""应用组装（spec: main-window）：初始化顺序与组件接线。

启动顺序（spec: app-paths / app-logging / app-config）：
路径 → 日志 → 配置 → 环境记录 → 服务与控制器 → 主窗口。
启动不加载模型（spec: ocr-engine 惰性加载）。

常驻改造（background-residency design D7 启动决策流）：
单实例检测（已有实例 → 请求其显示窗口后本次退出）→ 解除「最后一个
窗口关闭即退出」→ 托盘可用性 → 显示决策（登录自启/最小化配置驻留
托盘，托盘不可用时必须显示主窗口，不做隐形进程）→ 退出时释放全部
系统资源（spec: system-tray）。
"""

from __future__ import annotations

import logging
import sys
from typing import Sequence

from ocrtool.app import paths
from ocrtool.config import manager as config_manager_mod
from ocrtool.controllers.ocr_controller import OcrController
from ocrtool.ocr import model_manager
from ocrtool.ocr.service import OCRService
from ocrtool.platform.single_instance import (
    SingleInstanceGuard,
    SingleInstanceOutcome,
)
from ocrtool.ui.main_window import MainWindow
from ocrtool.ui.tray import TrayController
from ocrtool.utils import logger as app_logging

logger = logging.getLogger("ocrtool.app")

# 退出时等待后台识别收尾的上限：正常识别数秒内完成，超时强制退出
# 避免极端场景下进程杀不掉（spec: system-tray 识别进行中退出）
_SHUTDOWN_DRAIN_MS = 10_000


class ApplicationStartupError(RuntimeError):
    """组装失败（路径解析失败等），携带用户可读说明。"""


def bootstrap() -> tuple[OCRService, OcrController, object, list[str]]:
    """完成启动序列（不含 UI 事件循环），返回组装好的组件。

    返回 (服务, 控制器, 配置, 配置警告)。模型缺失不在此失败——自检只查
    存在性，明确的错误等到用户实际识别时呈现（spec: main-window）。
    """
    paths.initialize()  # PathResolutionError 由调用方转译为用户可读信息
    # 日志必须先于配置初挂（默认级）：配置加载期的错误（默认配置缺失、
    # 用户配置损坏）依赖 file handler 落盘（spec: app-config 记录错误日志）
    app_logging.setup_logging()
    config = config_manager_mod.load_config()
    app_logging.setup_logging(level=config.get("logging.level", "INFO"))
    app_logging.log_startup_environment(
        provider=config.get("runtime.provider", "CPUExecutionProvider"),
        cpu_threads=int(config.get("runtime.cpu_threads", 4)),
    )

    model = model_manager.resolve_model(paths.model_dir(), config.get("ocr.model"))
    if model is None:
        # 占位模型信息：界面状态区仍可组装，识别时报告模型缺失
        from ocrtool.ocr.model_manager import ModelInfo

        model = ModelInfo(
            model_id="<missing>",
            directory=paths.model_dir(),
            det_path=paths.model_dir() / "missing.onnx",
            rec_path=paths.model_dir() / "missing.onnx",
            name="模型缺失",
            recommended=False,
            language_coverage=(),
            raw={},
        )

    service = OCRService(model, cpu_threads=int(config.get("runtime.cpu_threads", 4)))
    controller = OcrController(service)
    assert not service.engine_loaded  # 启动不加载模型（spec: ocr-engine）
    return service, controller, config, list(config.warnings)


def create_main_window(
    controller: OcrController, config, warnings: list[str], *, tray_available: bool = False
) -> MainWindow:
    return MainWindow(
        controller, config, startup_warnings=warnings, tray_available=tray_available
    )


def should_show_main_window(
    argv: Sequence[str], config, tray_available: bool
) -> bool:
    """启动显示决策（design D7 启动决策流）。

    登录自启（--tray）或用户配置 start_minimized → 驻留托盘不显窗口；
    但托盘不可用时必须显示主窗口——否则成为用户无法访问的隐形进程
    （spec: auto-start / system-tray 降级）。
    """
    hidden = "--tray" in argv or bool(config.get("ui.start_minimized", False))
    if hidden:
        return not tray_available
    return True


def run(argv: Sequence[str] | None = None) -> int:
    """图形界面入口。"""
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication

    from ocrtool.main import window_title

    argv = list(sys.argv if argv is None else argv)
    try:
        service, controller, config, warnings = bootstrap()
    except paths.PathResolutionError as exc:
        # 日志系统依赖路径解析，此刻必然未初始化，只能写标准错误
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1

    try:
        app = QApplication(argv)
        # design D7：显式解除「无可见窗口即退出」——常驻期间进程只能经
        # 明确入口（托盘退出/关闭且不驻留）退出，两者是一组，不能只做一半
        app.setQuitOnLastWindowClosed(False)

        # 单实例：已有实例存活时传达激活意图后本次启动立即退出；
        # 登录自启（--tray）拉起的实例例外——不激活已有实例的窗口
        # （spec: auto-start 自启时已有实例在运行）
        guard = SingleInstanceGuard()
        if (
            guard.check_and_listen(activate_existing="--tray" not in argv)
            is SingleInstanceOutcome.ALREADY_RUNNING
        ):
            return 0

        # 开机启动路径自愈（design D8）：开启状态下用当前实际路径重写
        # 登录启动项，便携目录被移动后自启仍然有效
        from ocrtool.platform import autostart

        autostart.heal()

        tray = TrayController(
            window_title(),
            auto_start_enabled=autostart.is_enabled(),
            close_to_tray=bool(config.get("ui.close_to_tray", False)),
        )
        window = create_main_window(
            controller, config, warnings, tray_available=tray.available
        )

        window.quitRequested.connect(app.quit)
        guard.activationRequested.connect(window.bring_to_front)

        # 全局快捷键（spec: global-hotkey）：沿用配置组合注册；失败可见、
        # 不自行改用其他组合、不打断启动（状态区提示）
        hotkey = _register_hotkey_from_config(config, window)
        window.attach_hotkey(hotkey)

        if tray.available:
            tray.showRequested.connect(window.bring_to_front)
            tray.captureRequested.connect(window.start_region_capture)
            tray.quitRequested.connect(app.quit)
            tray.closeToTrayToggled.connect(window.set_close_to_tray)
            tray.autoStartToggled.connect(
                lambda on, t=tray: _apply_auto_start(on, config, window, t)
            )
        else:
            # 托盘不可用：降级为前台程序，关闭窗口即退出（spec: system-tray）
            logger.warning("托盘不可用，程序以前台模式运行")

        if should_show_main_window(argv, config, tray.available):
            window.show()

        def _release_resources() -> None:
            # 退出路径统一释放系统资源（spec: system-tray 退出时释放）：
            # 全局快捷键注销、实例端点、托盘图标、后台识别收尾
            hotkey.shutdown()
            guard.shutdown()
            tray.shutdown()
            QThreadPool.globalInstance().waitForDone(_SHUTDOWN_DRAIN_MS)

        app.aboutToQuit.connect(_release_resources)
    except Exception:
        # UI 组装异常必须有日志防护（还原旧 main.py 行为，review 50-4）
        logger.exception("启动失败：初始化界面时发生未预期异常")
        raise
    return app.exec()


def _register_hotkey_from_config(config, window):
    """按配置注册全局快捷键；任何失败都只在状态区可见（spec: global-hotkey）。"""
    from ocrtool.platform.hotkey import GlobalHotkey, HotkeyCombo

    hotkey = GlobalHotkey()
    combo_text = str(config.get("hotkey.capture", "") or "")
    try:
        combo = HotkeyCombo.parse(combo_text)
    except ValueError:
        logger.error("配置中的快捷键组合无法解析：%r", combo_text)
        window.notify(f"快捷键配置无效（{combo_text}），请通过工具栏「快捷键」重新设置")
        return hotkey
    if not hotkey.register(combo):
        logger.warning("启动时快捷键注册失败：%s", hotkey.last_error)
        window.notify(f"全局快捷键未生效：{hotkey.last_error}")
    return hotkey


def _apply_auto_start(enabled: bool, config, window, tray) -> None:
    """托盘「开机启动」切换：写/删登录启动项（spec: auto-start）。

    写入或移除失败时开关状态回退到实际生效的状态，MUST NOT 显示为已
    开启而实际未生效——勾选刷新以注册表真值为准（tray.set_auto_start_
    checked 不回灌信号）。
    """
    from ocrtool.platform import autostart

    try:
        if enabled:
            autostart.enable()
        else:
            autostart.disable()
    except autostart.AutoStartError as exc:
        logger.error("开机启动切换失败：%s", exc)
        window.notify(exc.args[0] if exc.args else str(exc))
    actual = autostart.is_enabled()
    tray.set_auto_start_checked(actual)
    config.set("system.auto_start", actual)
    config.save()
