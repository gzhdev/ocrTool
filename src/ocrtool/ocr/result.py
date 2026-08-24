"""引擎无关的识别结果契约（spec: ocr-engine）。

业务层只消费这里定义的结构，绝不接触 RapidOCR 的原生返回对象——
rapidocr 已在 2.x → 3.x 破坏性变更过一次，适配必须收敛在服务层单点
（design D1）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

Point = Tuple[float, float]


@dataclass(frozen=True)
class OcrLine:
    """单行识别条目。

    box 为四点位置框，处于「送入识别的图像」坐标系（可能已被等比缩放）；
    换算回原始图像坐标系需除以 OcrResult.scale。
    """

    text: str
    score: float
    box: Tuple[Point, Point, Point, Point]


def merge_line_texts(texts: Sequence[str]) -> str:
    """文本合并规则（spec: ocr-engine）：按行序以换行符连接，无版面重建。

    零行得到空字符串，单行得到该行文本，均不含多余换行符。
    """
    return "\n".join(texts)


@dataclass(frozen=True)
class OcrResult:
    """一次识别的完整结果。

    scale：送入识别的图像相对原始图像的等比缩放比例（原图被缩小到上限内时
    小于 1.0）。识别框绘制（result-box-overlay）消费此字段把位置框换算回
    原始图像坐标系——位置框处于缩放后坐标系，不记录该比例会导致绘制时
    整体错位。请勿删除（design D2）。
    """

    text: str
    lines: Tuple[OcrLine, ...]
    elapsed_ms: float
    width: int
    height: int
    scale: float = 1.0

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @classmethod
    def empty(
        cls, *, elapsed_ms: float, width: int, height: int, scale: float = 1.0
    ) -> "OcrResult":
        """空结果（识别成功但未检出文本）——与识别失败严格区分（spec: ocr-engine）。"""
        return cls(
            text="",
            lines=(),
            elapsed_ms=elapsed_ms,
            width=width,
            height=height,
            scale=scale,
        )
