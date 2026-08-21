"""依赖红线回归检查（spec: packaging — 禁止组件不得进入运行环境）。

pyside6-addons 含 QtWebEngine/QtMultimedia/Qt3D/QtCharts（设计书 §29）；
opencv-python 自带 Qt5 平台插件，与 PySide6 同进程冲突闪退。
从依赖侧断源是主防线，本测试保证该防线不被无意回退。
"""

from importlib.metadata import distributions

# 禁止出现的发行包：pyside6 元包/addons、非 headless 的 opencv 全系
FORBIDDEN_DISTS = {
    "pyside6",
    "pyside6-addons",
    "opencv-python",
    "opencv-contrib-python",
    "opencv-contrib-python-headless",
    "opencv-python-headless-samples",
}

# cv2 的唯一合法提供者
REQUIRED_DISTS = {"pyside6-essentials", "opencv-python-headless"}


def _normalize(name: str) -> str:
    """PEP 503 规范化：`PySide6_Essentials` 与 `pyside6-essentials` 视为同名。"""
    import re

    return re.sub(r"[-_.]+", "-", name).lower()


def _installed_dist_names() -> set[str]:
    return {_normalize(dist.metadata["Name"]) for dist in distributions() if dist.metadata["Name"]}


def test_forbidden_packages_absent() -> None:
    installed = _installed_dist_names()
    violated = FORBIDDEN_DISTS & installed
    assert not violated, (
        f"依赖红线被突破：环境中出现禁止包 {sorted(violated)}。"
        "请检查 pyproject.toml 的 [tool.uv] override-dependencies 是否被移除或改坏。"
    )


def test_required_packages_present() -> None:
    installed = _installed_dist_names()
    missing = REQUIRED_DISTS - installed
    assert not missing, f"缺少必需包 {sorted(missing)}，cv2/Qt 运行时将无法提供。"
