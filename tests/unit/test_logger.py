"""app-logging 单元测试：轮转、级别可配、初始化顺序、启动环境首段。"""

import logging
from pathlib import Path

import pytest

from ocrtool import __version__
from ocrtool.app import paths
from ocrtool.utils import logger as logger_mod


@pytest.fixture(autouse=True)
def _isolated_paths_and_logging(tmp_path, monkeypatch):
    """每个用例独立的 USER_ROOT 与 logger 状态。"""
    target = tmp_path / "user-root"
    target.mkdir()
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(target))
    paths.initialize()
    yield target
    paths.reset_for_tests()
    for handler in logger_mod.get_logger().handlers[:]:
        logger_mod.get_logger().removeHandler(handler)
        handler.close()


class TestSetupOrdering:
    """4.5 日志初始化发生在路径探测之后。"""

    def test_setup_requires_paths_initialized(self, monkeypatch):
        paths.reset_for_tests()
        with pytest.raises(RuntimeError, match="initialize"):
            logger_mod.setup_logging()
        paths.initialize()  # 恢复，供 fixture 清理


class TestRotation:
    """4.1 5 MB × 3 轮转：触发轮转且文件数量封顶。"""

    def test_rotation_triggers_and_caps_file_count(self):
        logger_mod.setup_logging()
        lg = logger_mod.get_logger()
        chunk = "x" * 60_000  # 单条 ~60KB
        for _ in range(380):  # 总量 ~22.8MB > 4×5MB，足以触发多次轮转并验证封顶
            lg.info("%s", chunk)
        for handler in lg.handlers:
            handler.flush()
        log_dir = paths.log_dir()
        files = sorted(p.name for p in log_dir.glob("ocrtool.log*"))
        assert files == [
            "ocrtool.log",
            "ocrtool.log.1",
            "ocrtool.log.2",
            "ocrtool.log.3",
        ]  # 最多 3 个历史文件，更早的被删除
        # 封顶后总大小不超过 4 × 5MB + 余量
        total = sum(p.stat().st_size for p in log_dir.glob("ocrtool.log*"))
        assert total < logger_mod.MAX_BYTES * 5


class TestLevelConfig:
    """4.1 / app-logging 级别可配置，默认 INFO。"""

    def test_default_info_excludes_debug(self):
        logger_mod.setup_logging()
        lg = logger_mod.get_logger()
        lg.debug("DEBUG_ONLY_MESSAGE")
        lg.info("INFO_MESSAGE")
        for handler in lg.handlers:
            handler.flush()
        content = (paths.log_dir() / "ocrtool.log").read_text(encoding="utf-8")
        assert "DEBUG_ONLY_MESSAGE" not in content
        assert "INFO_MESSAGE" in content

    def test_debug_level_includes_debug(self):
        logger_mod.setup_logging(level="DEBUG")
        lg = logger_mod.get_logger()
        lg.debug("DEBUG_ONLY_MESSAGE")
        for handler in lg.handlers:
            handler.flush()
        content = (paths.log_dir() / "ocrtool.log").read_text(encoding="utf-8")
        assert "DEBUG_ONLY_MESSAGE" in content


class TestStartupEnvironment:
    """4.2 启动首段包含全部环境字段。"""

    def test_startup_log_contains_all_fields(self):
        logger_mod.setup_logging()
        logger_mod.log_startup_environment(
            provider="CPUExecutionProvider", cpu_threads=4
        )
        for handler in logger_mod.get_logger().handlers:
            handler.flush()
        content = (paths.log_dir() / "ocrtool.log").read_text(encoding="utf-8")
        first_line = content.splitlines()[0]  # 日志文件为全新文件，首行即启动首段
        for field in (
            f"版本={__version__}",
            "操作系统=",
            "运行时=",
            "推理执行提供者=CPUExecutionProvider",
            "推理线程数=4",
            f"存储模式={paths.storage_mode().value}",
            f"可写状态根={paths.user_root()}",
        ):
            assert field in first_line, f"启动首段缺少字段: {field}"


class TestStartupExceptionRecording:
    """4.5 启动期异常写入最终日志文件。"""

    def test_startup_exception_lands_in_final_log(self):
        logger_mod.setup_logging()
        try:
            raise ValueError("人为制造的启动期异常")
        except ValueError:
            logger_mod.get_logger().exception("启动失败")
        for handler in logger_mod.get_logger().handlers:
            handler.flush()
        content = (paths.log_dir() / "ocrtool.log").read_text(encoding="utf-8")
        assert "人为制造的启动期异常" in content
        assert "Traceback" in content
        assert "ValueError" in content


class TestThirdPartyTakeover:
    """4.3 第三方 logger 接管：清空 handler、断开传播。"""

    def test_rapidocr_logger_silenced(self):
        # 模拟 rapidocr 给自己的 logger 挂上输出 handler
        third_party = logging.getLogger("RapidOCR")
        third_party.addHandler(logging.StreamHandler())
        third_party.propagate = True

        logger_mod.setup_logging()

        assert third_party.handlers == []
        assert third_party.propagate is False
