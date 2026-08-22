"""命令行端到端验证入口（mvp-image-ocr 任务 1.8，开发期临时脚本）。

用法：uv run python scripts/dev_e2e_ocr.py [样本图路径]
默认样本：tests/samples/mixed.png。输出识别行数与耗时，验证
「图像 → OCRService → OcrResult」全链路（不含 UI）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from ocrtool.app import paths  # noqa: E402
from ocrtool.config import manager as config_manager_mod  # noqa: E402
from ocrtool.ocr import model_manager  # noqa: E402
from ocrtool.ocr.service import OCRService  # noqa: E402
from ocrtool.utils import logger as app_logging  # noqa: E402

DEFAULT_SAMPLE = PROJECT_ROOT / "tests" / "samples" / "mixed.png"


def main() -> int:
    paths.initialize()
    app_logging.setup_logging()

    sample = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE
    with Image.open(sample) as img:
        image = np.asarray(img.convert("RGB"))[..., ::-1].copy()

    config = config_manager_mod.load_config()
    model = model_manager.resolve_model(paths.model_dir(), config.get("ocr.model"))
    if model is None:
        print("E2E FAIL: 无可用模型")
        return 1

    service = OCRService(model, cpu_threads=int(config.get("runtime.cpu_threads", 4)))
    start = time.perf_counter()
    result = service.recognize(image)
    total_ms = (time.perf_counter() - start) * 1000

    print(f"E2E OK: sample={sample.name} lines={result.line_count} "
          f"engine={result.elapsed_ms:.1f}ms total={total_ms:.1f}ms "
          f"size={result.width}x{result.height} scale={result.scale}")
    for line in result.lines:
        preview = line.text if len(line.text) <= 40 else line.text[:37] + "..."
        print(f"  [{line.score:.2f}] {preview}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
