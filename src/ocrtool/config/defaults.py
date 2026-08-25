"""内置默认配置（三层合并的第一层）。

字段集合必须与 `config/default.json` 完全一致（tests/unit/test_config.py 校验）。
注意：不含方向分类（use_orientation）开关——该能力已被移除，
配置中保留该项会暗示能力可被开启（spec: model-assets）。
"""

from typing import Any

BUILTIN_DEFAULTS: dict[str, Any] = {
    "ocr": {
        "model": "ppocrv6-small",
        "max_edge_px": 6000,
    },
    "runtime": {
        "provider": "CPUExecutionProvider",
        "cpu_threads": 4,
    },
    "logging": {
        "level": "INFO",
    },
    "ui": {
        # 识别成功且检出文本时自动复制（spec: main-window；空结果/失败不写）
        "auto_copy": True,
        # 识别位置框默认关闭——首次使用纯文本视图更简洁（design D5）
        "show_boxes": False,
        # 关闭主窗口 = 驻留托盘 / 退出程序（spec: system-tray）；默认退出，
        # 常驻由用户主动开启（background-residency design Open Question）
        "close_to_tray": False,
        # 启动即驻留托盘不显示主窗口（spec: auto-start），默认关
        "start_minimized": False,
        # 「已隐藏到托盘」一次性提示是否已给过（spec: system-tray）
        "tray_hint_done": False,
    },
    "hotkey": {
        # 全局快捷键组合（spec: global-hotkey），设计书 §3.4 建议值
        "capture": "Alt+Shift+A",
    },
    "system": {
        # 开机自启动开关（spec: auto-start），真实生效状态以注册表为准
        "auto_start": False,
    },
}
