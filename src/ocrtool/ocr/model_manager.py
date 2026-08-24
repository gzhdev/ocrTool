"""模型资产解析（spec: model-assets）。

目录契约：每个模型一个独立目录，含 model.json（描述）、det/rec 两个 ONNX。
唯一键是描述文件中的 id，与目录名解耦；目录名可自由携带版本信息。
解析回退链：配置指定 id → recommended → 扫描首个 → 自检失败。
禁网机制：引擎参数只经 to_engine_params() 生成——始终显式传入本地模型
路径并关闭方向分类，使推理组件的内建下载分支不可达。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("ocrtool.ocr")

DESCRIPTION_FILE = "model.json"
_REQUIRED_FIELDS = ("id", "name", "det_model", "rec_model", "language_coverage", "recommended")


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    directory: Path
    det_path: Path
    rec_path: Path
    name: str
    recommended: bool
    language_coverage: tuple[str, ...]
    raw: dict[str, Any]

    def to_engine_params(self) -> dict[str, Any]:
        """RapidOCR 构造参数——显式本地路径 + 关闭方向分类（禁用联网下载回退）。"""
        return {
            "Det.model_path": str(self.det_path),
            "Rec.model_path": str(self.rec_path),
            "Global.use_cls": False,
        }


@dataclass(frozen=True)
class ScanResult:
    models: tuple[ModelInfo, ...]
    errors: tuple[str, ...]


def _parse_description(directory: Path) -> tuple[ModelInfo | None, str | None]:
    """解析并校验单个 model.json；返回 (模型, 错误说明)。"""
    desc_path = directory / DESCRIPTION_FILE
    try:
        data = json.loads(desc_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"模型目录 {directory.name}：{DESCRIPTION_FILE} 缺失或无法解析（{exc}）"
    if not isinstance(data, dict):
        return None, f"模型目录 {directory.name}：{DESCRIPTION_FILE} 顶层必须是对象"

    missing = [f for f in _REQUIRED_FIELDS if f not in data]
    if missing:
        return None, f"模型目录 {directory.name}：{DESCRIPTION_FILE} 缺少字段 {missing}"
    if not isinstance(data["id"], str) or not data["id"].strip():
        return None, f"模型目录 {directory.name}：id 必须是非空字符串"
    if not isinstance(data["recommended"], bool):
        return None, f"模型目录 {directory.name}：recommended 必须是布尔值"
    coverage = data["language_coverage"]
    if not isinstance(coverage, list) or not all(isinstance(x, str) for x in coverage):
        return None, f"模型目录 {directory.name}：language_coverage 必须是字符串列表"
    if not isinstance(data["det_model"], str) or not isinstance(data["rec_model"], str):
        return None, f"模型目录 {directory.name}：det_model / rec_model 必须是文件名"

    # 模型文件必须位于本目录内（拒绝路径分隔符，防止越出模型目录）
    for field in ("det_model", "rec_model"):
        name = data[field]
        if Path(name).name != name:
            return None, f"模型目录 {directory.name}：{field} 必须是本目录内的文件名，而非路径"

    missing_files = [
        f"{field}={data[field]}"
        for field in ("det_model", "rec_model")
        if not (directory / data[field]).is_file()
    ]
    if missing_files:
        return None, f"模型目录 {directory.name}：模型文件缺失 {missing_files}"

    return (
        ModelInfo(
            model_id=data["id"].strip(),
            directory=directory,
            det_path=directory / data["det_model"],
            rec_path=directory / data["rec_model"],
            name=data["name"],
            recommended=data["recommended"],
            language_coverage=tuple(coverage),
            raw=data,
        ),
        None,
    )


def scan_models(models_root: Path) -> ScanResult:
    """扫描模型根目录；目录名排序保证「首个」回退的确定性。"""
    errors: list[str] = []
    models: list[ModelInfo] = []
    seen_ids: dict[str, str] = {}

    if not models_root.is_dir():
        return ScanResult(models=(), errors=(f"模型根目录不存在：{models_root}",))

    for directory in sorted(models_root.iterdir()):
        if not directory.is_dir():
            continue
        info, error = _parse_description(directory)
        if error:
            errors.append(error)
            continue
        assert info is not None
        if info.model_id in seen_ids:
            errors.append(
                f"模型 id 重复：{info.model_id}（目录 {seen_ids[info.model_id]} 与 "
                f"{directory.name} 声明了相同 id）——模型集合非法，不静默选择其一"
            )
            continue
        seen_ids[info.model_id] = directory.name
        models.append(info)

    # id 重复属于集合级非法：一旦发生，整个集合不可用（spec: model-assets）
    if any("id 重复" in e for e in errors):
        return ScanResult(models=(), errors=tuple(errors))
    return ScanResult(models=tuple(models), errors=tuple(errors))


def available_models(models_root: Path) -> list[ModelInfo]:
    """枚举全部可用模型（spec: model-assets 枚举可用模型）。

    每次调用都重新扫描：运行期放入新模型后再次请求即可见，无需重启
    （design D4）。只读描述文件并确认模型文件存在——完整性哈希校验的
    定位是获取流程的一环（fetch_models），枚举是高频交互操作，不做
    逐字节校验。不完整目录被跳过并记录日志（含原因）。
    """
    result = scan_models(models_root)
    for error in result.errors:
        logger.error("模型枚举：%s", error)
    return list(result.models)


def resolve_model(models_root: Path, configured_id: str | None) -> ModelInfo | None:
    """按回退链解析当前模型；无任何可用模型时返回 None（启动自检失败态）。"""
    result = scan_models(models_root)
    for error in result.errors:
        logger.error("模型扫描：%s", error)
    if not result.models:
        logger.error("无任何可用模型，启动自检失败；识别功能将在用户使用时报告错误")
        return None

    if configured_id:
        for info in result.models:
            if info.model_id == configured_id:
                return info
        logger.error("配置指定的模型不存在：%s，回退到推荐模型", configured_id)

    for info in result.models:
        if info.recommended:
            return info
    return result.models[0]
