"""model-assets 单元测试：目录契约、扫描完整性、id 解析回退链、锁文件哈希。"""

import hashlib
import json
from pathlib import Path

import pytest

from ocrtool.ocr import model_manager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_MODEL_DIR = PROJECT_ROOT / "models" / "ppocrv6-small"


def _write_model_dir(
    root: Path,
    dirname: str,
    *,
    model_id: str | None = "m1",
    recommended: bool = False,
    with_det: bool = True,
    with_rec: bool = True,
    with_description: bool = True,
    description_override: dict | None = None,
) -> Path:
    directory = root / dirname
    directory.mkdir(parents=True)
    if with_description:
        description: dict = {
            "id": model_id or dirname,
            "name": f"model {model_id or dirname}",
            "det_model": "det.onnx",
            "rec_model": "rec.onnx",
            "language_coverage": ["zh", "en"],
            "recommended": recommended,
        }
        if description_override:
            description.update(description_override)
        (directory / "model.json").write_text(
            json.dumps(description, ensure_ascii=False), encoding="utf-8"
        )
    if with_det:
        (directory / "det.onnx").write_bytes(b"det-bytes")
    if with_rec:
        (directory / "rec.onnx").write_bytes(b"rec-bytes")
    return directory


class TestDescriptionSchema:
    """6.1 model.json 结构校验（真实模型目录为样本）。"""

    @pytest.mark.skipif(
        not REAL_MODEL_DIR.is_dir(), reason="本地模型未落地"
    )
    def test_real_ppocrv6_small_description_is_valid(self, tmp_path):
        # 复制真实 model.json 与模型文件名占位到临时目录做结构校验
        directory = tmp_path / "ppocrv6-small"
        directory.mkdir()
        (directory / "model.json").write_bytes(
            (REAL_MODEL_DIR / "model.json").read_bytes()
        )
        (directory / "det.onnx").write_bytes(b"x")
        (directory / "rec.onnx").write_bytes(b"x")
        info, error = model_manager._parse_description(directory)
        assert error is None
        assert info is not None
        assert info.model_id == "ppocrv6-small"
        assert info.recommended is True
        assert info.language_coverage == ("zh", "en")

    def test_missing_fields_rejected(self, tmp_path):
        _write_model_dir(
            tmp_path, "bad", description_override={"det_model": None}
        )
        info, error = model_manager._parse_description(tmp_path / "bad")
        assert info is None and error is not None

    def test_path_traversal_rejected(self, tmp_path):
        _write_model_dir(
            tmp_path, "evil", description_override={"det_model": "../steal.onnx"}
        )
        info, error = model_manager._parse_description(tmp_path / "evil")
        assert info is None
        assert "文件名" in error


class TestScan:
    """6.2 目录扫描与完整性校验：完整 / 缺文件 / id 重复。"""

    def test_complete_directories_recognized(self, tmp_path):
        _write_model_dir(tmp_path, "a-dir", model_id="id-a")
        _write_model_dir(tmp_path, "b-dir", model_id="id-b", recommended=True)
        result = model_manager.scan_models(tmp_path)
        assert result.errors == ()
        assert [m.model_id for m in result.models] == ["id-a", "id-b"]

    def test_missing_files_reported(self, tmp_path, caplog):
        _write_model_dir(tmp_path, "incomplete", with_rec=False)
        _write_model_dir(tmp_path, "no-desc", with_description=False, with_rec=False)
        result = model_manager.scan_models(tmp_path)
        assert result.models == ()
        assert len(result.errors) == 2
        joined = "\n".join(result.errors)
        assert "rec_model=rec.onnx" in joined
        assert "model.json" in joined

    def test_duplicate_ids_invalidate_collection(self, tmp_path):
        _write_model_dir(tmp_path, "dir-one", model_id="dup")
        _write_model_dir(tmp_path, "dir-two", model_id="dup")
        result = model_manager.scan_models(tmp_path)
        assert result.models == ()  # 集合非法，不静默选择其一
        assert any("id 重复" in e for e in result.errors)

    def test_missing_root(self, tmp_path):
        result = model_manager.scan_models(tmp_path / "absent")
        assert result.models == ()
        assert result.errors


class TestResolveFallbackChain:
    """6.3 回退链四分支：配置 id → recommended → 首个 → 自检失败。"""

    def test_configured_id_found(self, tmp_path):
        _write_model_dir(tmp_path, "a", model_id="id-a")
        _write_model_dir(tmp_path, "b", model_id="id-b", recommended=True)
        resolved = model_manager.resolve_model(tmp_path, "id-a")
        assert resolved is not None and resolved.model_id == "id-a"

    def test_configured_id_missing_falls_back_to_recommended(self, tmp_path, caplog):
        _write_model_dir(tmp_path, "a", model_id="id-a")
        _write_model_dir(tmp_path, "b", model_id="id-b", recommended=True)
        with caplog.at_level("ERROR", logger="ocrtool.ocr"):
            resolved = model_manager.resolve_model(tmp_path, "ghost-id")
        assert resolved is not None and resolved.model_id == "id-b"
        assert any("ghost-id" in r.message for r in caplog.records)

    def test_no_recommended_falls_back_to_first(self, tmp_path):
        _write_model_dir(tmp_path, "b-second", model_id="id-b")
        _write_model_dir(tmp_path, "a-first", model_id="id-a")
        resolved = model_manager.resolve_model(tmp_path, None)
        # 目录名排序保证确定性
        assert resolved is not None and resolved.model_id == "id-a"

    def test_no_models_returns_none(self, tmp_path, caplog):
        with caplog.at_level("ERROR", logger="ocrtool.ocr"):
            resolved = model_manager.resolve_model(tmp_path, "whatever")
        assert resolved is None
        assert any("自检失败" in r.message for r in caplog.records)


class TestEngineParams:
    """6.6 引擎参数：显式本地路径 + 关闭方向分类。"""

    def test_to_engine_params(self, tmp_path):
        _write_model_dir(tmp_path, "a", model_id="id-a")
        info, error = model_manager._parse_description(tmp_path / "a")
        assert error is None and info is not None
        params = info.to_engine_params()
        assert params["Det.model_path"] == str(tmp_path / "a" / "det.onnx")
        assert params["Rec.model_path"] == str(tmp_path / "a" / "rec.onnx")
        assert params["Global.use_cls"] is False
        assert len(params) == 3


class TestLockFileHashes:
    """6.4 models.lock.json 登记的哈希与实际文件一致（本地已落地时）。"""

    @pytest.mark.skipif(
        not (REAL_MODEL_DIR / "det.onnx").exists()
        or not (REAL_MODEL_DIR / "rec.onnx").exists(),
        reason="本地模型未落地（运行 scripts/fetch_models.ps1 后重试）",
    )
    def test_registered_hashes_match_local_files(self):
        lock = json.loads(
            (PROJECT_ROOT / "packaging" / "models.lock.json").read_text(
                encoding="utf-8"
            )
        )
        entry = lock["models"]["ppocrv6-small"]
        for kind in ("det", "rec"):
            actual = hashlib.sha256(
                (REAL_MODEL_DIR / entry[kind]["file"]).read_bytes()
            ).hexdigest()
            assert actual == entry[kind]["sha256"], f"{kind} 哈希与登记值不符"
