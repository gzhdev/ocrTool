"""ocr/result.py：结果契约、文本合并规则与空结果表达（任务 1.1 / 1.2）。"""

from ocrtool.ocr.result import OcrLine, OcrResult, merge_line_texts


def make_line(text: str = "行", score: float = 0.9) -> OcrLine:
    return OcrLine(
        text=text, score=score, box=((0, 0), (10, 0), (10, 5), (0, 5))
    )


class TestOcrResult:
    def test_字段完整性与取值(self):
        lines = (make_line("第一行", 0.91), make_line("第二行", 0.87))
        result = OcrResult(
            text="第一行\n第二行",
            lines=lines,
            elapsed_ms=123.4,
            width=800,
            height=600,
            scale=0.5,
        )
        assert result.text == "第一行\n第二行"
        assert result.line_count == 2
        assert result.lines[0].text == "第一行"
        assert result.lines[0].score == 0.91
        assert result.lines[1].box == ((0, 0), (10, 0), (10, 5), (0, 5))
        assert result.elapsed_ms == 123.4
        assert (result.width, result.height) == (800, 600)
        assert result.scale == 0.5

    def test_scale_默认值为_1(self):
        result = OcrResult(
            text="", lines=(), elapsed_ms=1.0, width=10, height=10
        )
        assert result.scale == 1.0

    def test_空结果工厂(self):
        result = OcrResult.empty(elapsed_ms=5.0, width=320, height=240)
        assert result.text == ""
        assert result.lines == ()
        assert result.line_count == 0
        assert result.elapsed_ms == 5.0
        assert (result.width, result.height) == (320, 240)
        assert result.scale == 1.0


class TestMergeLineTexts:
    def test_多行按序以换行连接(self):
        assert merge_line_texts(["甲", "乙", "丙"]) == "甲\n乙\n丙"

    def test_单行无多余换行(self):
        assert merge_line_texts(["only"]) == "only"

    def test_零行得到空字符串(self):
        assert merge_line_texts([]) == ""
