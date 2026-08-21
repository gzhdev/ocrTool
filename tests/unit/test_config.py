"""app-config 单元测试：字段集合一致、三层合并回落、损坏降级、未知字段保留。"""

import json
from pathlib import Path

import pytest

from ocrtool.config import manager as config_manager_mod
from ocrtool.config.defaults import BUILTIN_DEFAULTS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_DEFAULT_JSON = PROJECT_ROOT / "config" / "default.json"


def _field_keys(values: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in values.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys |= _field_keys(value, dotted)
        else:
            keys.add(dotted)
    return keys


class TestSchemaConsistency:
    """5.1 内置默认值与 config/default.json 字段集合一致，且无方向分类项。"""

    def test_builtin_and_file_have_identical_field_sets(self):
        file_values = json.loads(REPO_DEFAULT_JSON.read_text(encoding="utf-8"))
        assert _field_keys(BUILTIN_DEFAULTS) == _field_keys(file_values)

    def test_values_also_consistent(self):
        file_values = json.loads(REPO_DEFAULT_JSON.read_text(encoding="utf-8"))
        assert BUILTIN_DEFAULTS == file_values

    def test_no_orientation_switch_anywhere(self):
        blob = (
            json.dumps(BUILTIN_DEFAULTS)
            + REPO_DEFAULT_JSON.read_text(encoding="utf-8").lower()
        )
        for banned in ("use_orientation", "orientation", "use_cls"):
            assert banned not in blob, f"配置中不得出现方向分类相关字段：{banned}"


class TestThreeLayerMerge:
    """5.2 三层优先级与各层缺失时的回落。"""

    def test_user_layer_wins(self, tmp_path):
        default_file = tmp_path / "default.json"
        default_file.write_text(
            json.dumps({"ocr": {"model": "from-default-file"}}), encoding="utf-8"
        )
        user_file = tmp_path / "config.json"
        user_file.write_text(
            json.dumps({"ocr": {"model": "from-user"}}), encoding="utf-8"
        )
        mgr = config_manager_mod.load_config(default_file, user_file)
        assert mgr.get("ocr.model") == "from-user"

    def test_missing_user_key_falls_back_to_default_file(self, tmp_path):
        default_file = tmp_path / "default.json"
        default_file.write_text(
            json.dumps({"logging": {"level": "WARNING"}}), encoding="utf-8"
        )
        user_file = tmp_path / "config.json"
        user_file.write_text(json.dumps({"ocr": {"model": "x"}}), encoding="utf-8")
        mgr = config_manager_mod.load_config(default_file, user_file)
        assert mgr.get("logging.level") == "WARNING"

    def test_missing_default_file_falls_back_to_builtin(self, tmp_path):
        user_file = tmp_path / "config.json"
        user_file.write_text(json.dumps({"ocr": {"model": "x"}}), encoding="utf-8")
        mgr = config_manager_mod.load_config(tmp_path / "absent.json", user_file)
        assert mgr.get("logging.level") == "INFO"  # 内置默认值
        assert mgr.get("ocr.model") == "x"

    def test_first_run_generates_user_config(self, tmp_path):
        default_file = tmp_path / "default.json"
        default_file.write_text(json.dumps({"ocr": {"model": "m1"}}), encoding="utf-8")
        user_file = tmp_path / "data" / "config.json"
        mgr = config_manager_mod.load_config(default_file, user_file)
        assert user_file.exists()
        persisted = json.loads(user_file.read_text(encoding="utf-8"))
        assert persisted == mgr.values


class TestCorruptionDegradation:
    """5.3 损坏降级：备份、默认值启动、记录错误。"""

    def test_invalid_json_backed_up_and_defaults_used(self, tmp_path):
        default_file = tmp_path / "default.json"
        default_file.write_text(json.dumps({"ocr": {"model": "file-m"}}), encoding="utf-8")
        user_file = tmp_path / "config.json"
        user_file.write_text("{ not valid json !!!", encoding="utf-8")

        mgr = config_manager_mod.load_config(default_file, user_file)

        assert mgr.get("ocr.model") == "file-m"  # 以默认配置继续启动
        backups = list(tmp_path.glob("config.json.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "{ not valid json !!!"
        assert not user_file.exists()
        assert any("重置" in w for w in mgr.warnings)

    def test_non_dict_top_level_treated_as_corrupt(self, tmp_path):
        user_file = tmp_path / "config.json"
        user_file.write_text("[1, 2, 3]", encoding="utf-8")
        mgr = config_manager_mod.load_config(tmp_path / "absent.json", user_file)
        assert mgr.get("logging.level") == "INFO"
        assert list(tmp_path.glob("config.json.corrupt-*"))


class TestUnknownFieldPreservation:
    """5.4 写回时保留未识别字段（读到更高版本写入的配置）。"""

    def test_unknown_fields_survive_roundtrip(self, tmp_path):
        user_file = tmp_path / "config.json"
        user_file.write_text(
            json.dumps(
                {
                    "ocr": {"model": "user-model"},
                    "future_feature": {"enabled": True, "nested": {"a": 1}},
                }
            ),
            encoding="utf-8",
        )
        mgr = config_manager_mod.load_config(tmp_path / "absent.json", user_file)
        mgr.set("ocr.model", "changed-by-app")
        mgr.save()

        persisted = json.loads(user_file.read_text(encoding="utf-8"))
        assert persisted["ocr"]["model"] == "changed-by-app"
        assert persisted["future_feature"] == {"enabled": True, "nested": {"a": 1}}
