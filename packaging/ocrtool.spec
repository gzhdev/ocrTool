# -*- mode: python ; coding: utf-8 -*-
"""OCRTool 打包配置单一来源（取代设计书 §31 的命令行方案）。

契约（见 openspec specs/packaging）：
- rapidocr 的 config.yaml / default_models.yaml / 字典与自带模型必须进包；
- models/ 与 config/ 不得进入 datas，由构建脚本复制到 exe 平级；
- 禁止组件（WebEngine/Multimedia/Qml/Quick/3D/Charts 等）在依赖侧已断源，
  excludes 仅作第二道防线。
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ENTRY_SCRIPT = os.path.join(PROJECT_ROOT, "src", "ocrtool", "main.py")

datas = collect_data_files("rapidocr")
hiddenimports = collect_submodules("rapidocr")

excludes = [
    # 设计书 §29 禁止的界面组件（第二道防线，主防线是 pyside6-essentials 依赖断源）
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.QtCharts",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    # 本项目不使用的标准库组件
    "tkinter",
]

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[os.path.join(PROJECT_ROOT, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OCRTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI 应用：双击启动不得弹出控制台窗口；--self-test 的 stdout 在被管道重定向时仍有效
    disable_windowed_traceback=False,
    contents_directory="_runtime",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="OCRTool",
)
