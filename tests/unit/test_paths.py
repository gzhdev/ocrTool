"""app-paths 单元测试：双根解析、实写探针、环境变量覆盖、按需建目录。"""

import os
import sys
from pathlib import Path

import pytest

from ocrtool.app import paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_paths_state():
    yield
    paths.reset_for_tests()


class TestGetAppRoot:
    """3.1 开发/打包两种环境下的根目录取值。"""

    def test_dev_environment_resolves_to_project_root(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        root = paths.get_app_root()
        assert root == PROJECT_ROOT
        assert (root / "pyproject.toml").exists()
        assert (root / "src" / "ocrtool").is_dir()

    def test_frozen_environment_resolves_to_exe_directory(
        self, monkeypatch, tmp_path
    ):
        exe_dir = tmp_path / "OCRTool"
        exe_dir.mkdir()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_dir / "OCRTool.exe"))
        assert paths.get_app_root() == exe_dir


class TestProbeWritable:
    """3.2 基于实际写入的探针：可写/不可写两情形 + 无残留 + 不依赖 os.access。"""

    def test_writable_directory(self, tmp_path, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("os.access must not be used")

        monkeypatch.setattr(os, "access", _boom)
        assert paths.probe_writable(tmp_path) is True
        assert list(tmp_path.iterdir()) == []  # 探测不留残留

    def test_missing_directory_not_writable(self, tmp_path):
        assert paths.probe_writable(tmp_path / "nope") is False
        assert not (tmp_path / "nope").exists()

    def test_file_in_the_way_not_writable(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        assert paths.probe_writable(blocker, create=True) is False
        assert blocker.read_text(encoding="utf-8") == "x"  # 原文件未被破坏

    def test_create_flag_makes_missing_directory_writable(self, tmp_path):
        target = tmp_path / "deep" / "dir"
        assert paths.probe_writable(target, create=True) is True
        assert target.is_dir()
        assert list(target.iterdir()) == []


class TestResolveUserRoot:
    """探测顺序与存储模式判定。"""

    def test_portable_when_app_root_writable(self, tmp_path):
        root, mode = paths.resolve_user_root(tmp_path, {})
        assert root == tmp_path
        assert mode is paths.StorageMode.PORTABLE
        assert list(tmp_path.iterdir()) == []  # 探测文件已清理

    def test_installed_fallback_to_localappdata(self, tmp_path):
        unwritable_app_root = tmp_path / "missing"
        local = tmp_path / "LocalAppData"
        root, mode = paths.resolve_user_root(
            unwritable_app_root, {"LOCALAPPDATA": str(local)}
        )
        assert root == local / "OCRTool"
        assert mode is paths.StorageMode.INSTALLED
        assert (local / "OCRTool").is_dir()


class TestOverrideEnv:
    """3.3 OCRTOOL_DATA_DIR 覆盖：有效采用 / 无效启动失败。"""

    def test_valid_override_takes_precedence(self, tmp_path):
        target = tmp_path / "explicit-data"
        target.mkdir()
        # app_root 同样可写，但覆盖优先级更高，自动探测必须被跳过
        root, mode = paths.resolve_user_root(
            tmp_path, {paths.ENV_DATA_DIR: str(target)}
        )
        assert root == target
        assert mode is paths.StorageMode.OVERRIDE

    def test_invalid_override_fails_with_clear_reason(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        bad_target = str(blocker / "sub")
        with pytest.raises(paths.PathResolutionError, match=paths.ENV_DATA_DIR):
            paths.resolve_user_root(
                tmp_path, {paths.ENV_DATA_DIR: bad_target}
            )

    def test_blank_override_treated_as_unset(self, tmp_path):
        root, mode = paths.resolve_user_root(tmp_path, {paths.ENV_DATA_DIR: "  "})
        assert root == tmp_path
        assert mode is paths.StorageMode.PORTABLE


class TestInitialize:
    """3.4 可写目录按需创建 + 访问器。"""

    def test_creates_data_logs_cache_on_first_run(self, tmp_path):
        target = tmp_path / "user-root"
        target.mkdir()
        cfg = paths.initialize({paths.ENV_DATA_DIR: str(target)})
        assert cfg.user_root == target
        for name in ("data", "logs", "cache"):
            assert (target / name).is_dir()

    def test_accessors_require_initialize(self):
        with pytest.raises(RuntimeError, match="initialize"):
            paths.user_root()

    def test_accessor_layout(self, tmp_path):
        target = tmp_path / "user-root"
        target.mkdir()
        paths.initialize({paths.ENV_DATA_DIR: str(target)})
        assert paths.user_config_path() == target / "data" / "config.json"
        assert paths.log_dir() == target / "logs"
        assert paths.cache_dir() == target / "cache"
        assert paths.model_dir().name == "models"
        assert paths.default_config_path().name == "default.json"
        assert paths.storage_mode() is paths.StorageMode.OVERRIDE
