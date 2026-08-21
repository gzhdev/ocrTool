"""发布冒烟编码回归（review.md 问题 3.1）。

Python 3.13 在重定向下 stdout 采用本地 ANSI 代码页 + strict（PEP 686 的
UTF-8 默认要到 3.15），非 CJK 代码页机器上 `--self-test` 打印中文识别文本
会 UnicodeEncodeError，令 release.ps1 冒烟关卡误判失败。本测试以
PYTHONIOENCODING=cp1252 在任意代码页的开发机上确定性复现 en-US 条件。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

requires_local_models = pytest.mark.skipif(
    not (PROJECT_ROOT / "models" / "ppocrv6-small" / "det.onnx").exists(),
    reason="本地模型未落地（运行 scripts/fetch_models.ps1 后重试）",
)

_RUNNER = "from ocrtool.main import run_self_test; raise SystemExit(run_self_test())"


@requires_local_models
def test_selftest_survives_non_cjk_codepage(tmp_path):
    env = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",  # 模拟 en-US 机器重定向 stdout 的编码
        "OCRTOOL_DATA_DIR": str(tmp_path),  # 隔离 USER_ROOT，避免污染仓库根
    }
    result = subprocess.run(
        [sys.executable, "-c", _RUNNER],
        capture_output=True,
        env=env,
        cwd=str(tmp_path),
    )
    stderr = result.stderr.decode("utf-8", errors="replace")
    assert result.returncode == 0, f"self-test 在 cp1252 下崩溃：\n{stderr}"
    assert b"SELF-TEST OK" in result.stdout
    # 中文识别文本应以 UTF-8 字节完整落地，而非编码崩溃或被丢弃
    assert "中英文混合识别冒烟验收".encode("utf-8") in result.stdout
