"""packaging 版本一致性测试：版本号单一来源与三处消费（包名/日志/界面）。"""

import re
from pathlib import Path

from ocrtool import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_version_format_is_semver_like() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_window_title_shows_version() -> None:
    """界面显示位：窗口标题携带单一来源版本号。"""
    from ocrtool.main import window_title

    assert __version__ in window_title()
    assert window_title().startswith("OCRTool")


def test_startup_log_shows_version(tmp_path, monkeypatch) -> None:
    """启动日志位：首段「版本=」字段来自同一 __version__。"""
    from ocrtool.app import paths
    from ocrtool.utils import logger as logger_mod

    target = tmp_path / "user-root"
    target.mkdir()
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(target))
    paths.initialize()
    try:
        logger_mod.setup_logging()
        logger_mod.log_startup_environment(provider="CPU", cpu_threads=1)
        for handler in logger_mod.get_logger().handlers:
            handler.flush()
        content = (paths.log_dir() / "ocrtool.log").read_text(encoding="utf-8")
        assert f"版本={__version__}" in content
    finally:
        paths.reset_for_tests()
        for handler in logger_mod.get_logger().handlers[:]:
            logger_mod.get_logger().removeHandler(handler)
            handler.close()


def test_release_script_zip_naming_follows_single_source() -> None:
    """发布包名位：release.ps1 的 ZIP 命名由 __version__ 拼接（OCRTool-<版本>-win-x64.zip）。"""
    release_ps1 = (PROJECT_ROOT / "scripts" / "release.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert 'OCRTool-$version-win-x64.zip' in release_ps1
    assert "__version__" in release_ps1  # 版本号解析自单一来源文件


def test_pyproject_version_in_sync() -> None:
    """防止 pyproject 与 __version__ 漂移（第四处出现版本号的文件）。"""
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in pyproject
