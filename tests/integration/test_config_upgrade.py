"""app-config 集成测试：程序目录被整体替换后用户配置仍然生效（spec: app-config）。"""

import json
import shutil
from pathlib import Path

from ocrtool.config import manager as config_manager_mod


def test_user_config_survives_app_dir_replacement(tmp_path):
    # 第一代程序目录 + 独立的用户数据目录
    app_dir_v1 = tmp_path / "app-v1"
    user_dir = tmp_path / "user-data"
    app_dir_v1.mkdir()
    (app_dir_v1 / "config").mkdir()
    (app_dir_v1 / "config" / "default.json").write_text(
        json.dumps({"logging": {"level": "INFO"}}), encoding="utf-8"
    )
    user_config = user_dir / "data" / "config.json"

    # 首次启动：生成用户配置，用户随后修改了一项设置
    mgr = config_manager_mod.load_config(
        app_dir_v1 / "config" / "default.json", user_config
    )
    mgr.set("logging.level", "DEBUG")
    mgr.set("ocr.model", "my-favorite-model")
    mgr.save()

    # 升级：程序目录整体替换为 v2（全新目录、全新默认配置文件）
    app_dir_v2 = tmp_path / "app-v2"
    (app_dir_v2 / "config").mkdir(parents=True)
    (app_dir_v2 / "config" / "default.json").write_text(
        json.dumps({"logging": {"level": "INFO"}}), encoding="utf-8"
    )

    mgr2 = config_manager_mod.load_config(
        app_dir_v2 / "config" / "default.json", user_config
    )
    assert mgr2.get("logging.level") == "DEBUG"
    assert mgr2.get("ocr.model") == "my-favorite-model"

    # v1 目录删除也不影响（用户配置与其无任何关联）
    shutil.rmtree(app_dir_v1)
    mgr3 = config_manager_mod.load_config(
        app_dir_v2 / "config" / "default.json", user_config
    )
    assert mgr3.get("logging.level") == "DEBUG"
