"""内置默认配置（三层合并的第一层）。

字段集合必须与 `config/default.json` 完全一致（tests/unit/test_config.py 校验）。
注意：不含方向分类（use_orientation）开关——该能力已被移除，
配置中保留该项会暗示能力可被开启（spec: model-assets）。
"""

from typing import Any

BUILTIN_DEFAULTS: dict[str, Any] = {
    "ocr": {
        "model": "ppocrv6-small",
    },
    "runtime": {
        "provider": "CPUExecutionProvider",
        "cpu_threads": 4,
    },
    "logging": {
        "level": "INFO",
    },
}
