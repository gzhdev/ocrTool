"""配置管理（spec: app-config）。

三层优先级合并：内置默认值 → 随程序分发的 config/default.json → 用户配置
（USER_ROOT/data/config.json）。用户配置独立于程序目录，升级替换程序目录
不会覆盖它；损坏时备份降级而非启动失败；写回时保留未识别字段。
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ocrtool.app import paths
from ocrtool.config.defaults import BUILTIN_DEFAULTS

logger = logging.getLogger("ocrtool.config")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并：override 中同名项覆盖 base；嵌套 dict 逐层合并。"""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class ConfigManager:
    """加载、持有并持久化生效配置。"""

    def __init__(
        self,
        default_path: Path | None = None,
        user_path: Path | None = None,
    ) -> None:
        self._default_path = default_path or paths.default_config_path()
        self._user_path = user_path or paths.user_config_path()
        self._values: dict[str, Any] = {}
        # 供界面状态区展示的启动期提示（如「用户配置已重置」）
        self.warnings: list[str] = []

    @property
    def values(self) -> dict[str, Any]:
        return self._values

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self._values
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        node = self._values
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def load(self) -> "ConfigManager":
        """执行三层合并并生成首运行用户配置。"""
        merged: dict[str, Any] = copy.deepcopy(BUILTIN_DEFAULTS)

        file_defaults = self._load_json(self._default_path)
        if file_defaults is None:
            if not self._default_path.exists():
                logger.error("默认配置文件缺失：%s，使用内置默认值", self._default_path)
            else:
                logger.error(
                    "默认配置文件无法解析：%s，使用内置默认值", self._default_path
                )
        elif not isinstance(file_defaults, dict):
            logger.error(
                "默认配置文件结构不符合预期（顶层应为对象）：%s，使用内置默认值",
                self._default_path,
            )
        else:
            merged = deep_merge(merged, file_defaults)

        if self._user_path.exists():
            user_values = self._load_json(self._user_path)
            if not isinstance(user_values, dict):
                backup = self._backup_corrupt()
                logger.error(
                    "用户配置文件损坏（非法 JSON 或顶层非对象），已备份至 %s，"
                    "本次以默认配置启动",
                    backup,
                )
                self.warnings.append(
                    f"用户配置已重置（原文件备份为 {backup.name}）"
                )
                # user_values 保持 None：不合并损坏内容
            else:
                merged = deep_merge(merged, user_values)
        else:
            # 首次运行：以当前生效配置为内容生成用户配置文件
            self._write_json(self._user_path, merged)
            logger.info("首次运行，已生成用户配置：%s", self._user_path)

        self._values = merged
        return self

    def save(self) -> None:
        """写回用户配置。未识别字段因合并语义天然保留（spec: app-config）。"""
        self._user_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(self._user_path, self._values)

    def _backup_corrupt(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self._user_path.with_suffix(".json.corrupt-" + timestamp)
        counter = 1
        while backup.exists():
            backup = self._user_path.with_suffix(
                f".json.corrupt-{timestamp}-{counter}"
            )
            counter += 1
        self._user_path.replace(backup)
        return backup

    @staticmethod
    def _load_json(path: Path) -> Any | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write_json(path: Path, values: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def load_config(
    default_path: Path | None = None, user_path: Path | None = None
) -> ConfigManager:
    return ConfigManager(default_path, user_path).load()
