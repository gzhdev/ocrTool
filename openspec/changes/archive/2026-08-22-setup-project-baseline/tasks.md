## 1. 打包 Spike（风险前置，失败则暂停后续全部工作）

- [x] 1.1 建立最小 `pyproject.toml`：`requires-python = ">=3.13,<3.14"`，依赖 `pyside6-essentials` / `onnxruntime` / `rapidocr` / `pyinstaller`，并配置 `[tool.uv] override-dependencies` 覆盖 `opencv-python-headless`；验证 `uv sync` 成功且 `uv pip list` 中不含 `pyside6-addons` 与 `opencv-python`
- [x] 1.2 手工放置一份 PP-OCRv6 Small 的 det/rec 模型到 `models/ppocrv6-small/`；验证目录内文件清单，并据此确认 design.md Open Question「识别模型是否自带字符字典」的答案，将结论回写 design.md
- [x] 1.3 写最小骨架 `src/ocrtool/main.py`：创建空窗口、显式传入本地模型路径调用一次识别、打印行数后退出；验证在开发环境下 `uv run` 可跑通且全程无网络请求
- [x] 1.4 写 `packaging/ocrtool.spec`：含 `collect_data_files("rapidocr")`、`collect_submodules("rapidocr")`、组件 `excludes`、`contents-directory = "_runtime"`；验证 `pyinstaller packaging/ocrtool.spec` 产出 `dist/OCRTool/OCRTool.exe`
- [x] 1.5 手工将 `models/` 与 `config/` 复制到 `dist/OCRTool/` 与 exe 平级；验证产物目录结构符合设计书 §7
- [x] 1.6 在无 Python 环境的 Windows 10/11 x64 机器（或干净容器）上运行产物；验证窗口正常显示、识别输出文本、无 Qt 平台插件冲突、无第三方组件数据文件缺失报错（实施注记：以净化环境等价验证——PATH 仅系统目录、无任何 Python、代理指向死端口，四项检查全过、退出码 0；真机冒烟由 7.6 脚本化为发布强制关卡）
- [x] 1.7 记录产物体积与冷启动耗时，回写 design.md Open Question 第二条；若显著偏离设计书 §27 参考目标则在此处说明原因（351 MB 超预估已说明原因；耗时满足 §27 目标）
- [x] 1.8 **决策关卡**：确认 spike 通过。若失败，停止本变更并重新评估技术选型；若通过，删除最小骨架中的临时代码，进入任务组 2（spike 通过：依赖解析、本地模型识别、PyInstaller 产物、净化环境运行全部验证；临时代码保留至任务组 3-5 由正式入口替换，见下）

## 2. 依赖基线固化

- [x] 2.1 补全 `pyproject.toml` 的项目元数据、`src` 布局配置与开发依赖（pytest）；验证 `uv sync --frozen` 成功
- [x] 2.2 提交 `uv.lock`；验证在另一份干净 checkout 上 `uv sync --frozen` 可复现完全相同的依赖版本（实施注记：`git clone` 至临时目录后 `--frozen` 同步成功，`uv pip freeze` 与原环境逐行一致，唯一差异为各自的 editable 自引用路径行）
- [x] 2.3 在 `.gitignore` 中排除 `models/**/*.onnx` 并显式保留 `models/**/model.json`；验证 `git status` 中模型权重不出现、`model.json` 出现（实施注记：`git check-ignore` 验证 onnx 命中排除规则、`model.json` 不被忽略、`packaging/ocrtool.spec` 因新增 `!` 规则入库；`model.json` 文件在 6.1 落地后由该任务复核 git status 可见性）
- [x] 2.4 添加依赖约束的回归检查（脚本或测试）：断言已解析依赖中不含 `pyside6-addons` 与非 headless 的 `opencv-python`；验证该检查在故意还原依赖时会失败（实施注记：`tests/unit/test_dependency_constraints.py` 红绿实证——注入 opencv-python 后测试失败并给出中文原因，`uv sync` 还原后通过；附带发现 uv 的 override 对项目目录内的 `uv pip install` 亦有保护）

## 3. 路径与存储模式

- [x] 3.1 实现 `app/paths.py` 的双根解析（`APP_ROOT` / `USER_ROOT`）与开发/打包环境判别；验证单元测试覆盖两种环境下的根目录取值
- [x] 3.2 实现基于实际写入的可写性探针（含探测后清理）；验证单元测试模拟可写与不可写两种情形，且确认未使用 `os.access`（实施注记：测试将 `os.access` 替换为抛错函数后探针仍正确判定，证明不依赖权限位）
- [x] 3.3 实现 `OCRTOOL_DATA_DIR` 覆盖，无效时以明确原因终止启动；验证单元测试覆盖「有效覆盖」「无效覆盖导致启动失败」两个场景
- [x] 3.4 实现可写目录的按需创建；验证首次运行后 `data` / `logs` / `cache` 目录存在
- [x] 3.5 添加「不依赖当前工作目录」的集成测试：从其他磁盘目录启动进程；验证路径解析结果与从程序目录启动时一致

## 4. 日志

- [x] 4.1 实现 `utils/logger.py`：日志落 `USER_ROOT/logs`、5 MB × 3 轮转、级别可配；验证单元测试确认轮转触发与文件数量上限
- [x] 4.2 实现启动环境信息记录（版本、OS、运行时、provider、线程数、存储模式、`USER_ROOT` 实际路径）；验证启动后日志首段包含全部字段
- [x] 4.3 实现第三方 OCR 组件 logger 的接管（清空 handler、断开传播）；验证集成测试执行一次识别后，日志与标准输出中均不含识别文本
- [x] 4.4 添加隐私回归测试：在 DEBUG 级别下执行识别；验证日志仅含尺寸、行数、耗时，不含任何识别文本
- [x] 4.5 确认日志初始化发生在路径探测之后；验证启动期人为制造异常时，该异常能被写入最终日志文件（实施注记：`setup_logging` 通过 `paths.log_dir()` 强制该顺序——未初始化路径即抛错；`main.py` 中路径→日志→环境的顺序已接线）

## 5. 配置

- [x] 5.1 定义内置默认值与 `config/default.json`（不含方向分类开关）；验证两者字段集合一致的测试通过
- [x] 5.2 实现三层优先级合并与首次运行生成用户配置；验证单元测试覆盖三层各自缺失时的回落行为
- [x] 5.3 实现配置损坏降级：备份损坏文件、以默认值启动、记录错误；验证注入非法 JSON 后程序仍能启动且备份文件存在（实施注记：「界面状态区提示」由 `ConfigManager.warnings` 承载，UI 状态栏随 mvp-image-ocr 落地时消费）
- [x] 5.4 实现写回时保留未识别字段；验证单元测试确认额外字段在读写往返后仍然存在
- [x] 5.5 添加升级不覆盖用户配置的集成测试：模拟替换程序目录后启动；验证用户配置项依然生效

## 6. 模型资产

- [x] 6.1 定义 `model.json` 结构（含 `id` / 模型文件名 / `languages` 语义修正 / `recommended`）并为 `ppocrv6-small` 落地一份；验证结构校验测试通过（实施注记：语义修正落地为字段更名 `languages` → `language_coverage`，并附 note 说明统一多语种语义）
- [x] 6.2 实现模型目录扫描与完整性校验（缺文件、id 重复的处理）；验证单元测试覆盖完整、缺文件、id 重复三种情形
- [x] 6.3 实现模型解析回退链（配置 id → recommended → 首个 → 自检失败）；验证单元测试逐级覆盖四个分支（目录名排序保证「首个」的确定性）
- [x] 6.4 编写 `packaging/models.lock.json`，SHA256 取自 rapidocr 上游 `default_models.yaml`；验证登记的哈希与实际文件一致
- [x] 6.5 实现 `scripts/fetch_models.ps1`（幂等、校验、失败即删）；验证连续执行两次第二次全部跳过，且篡改文件后重跑会删除并报错（实施注记：ps1 需 UTF-8 BOM，否则 Windows PowerShell 5.1 将中文字符按 ANSI 误解析导致语法错误）
- [x] 6.6 确认引擎调用始终显式传入本地模型路径且关闭方向分类；验证断网环境下识别成功，且模型缺失时报本地路径错误而非发起下载（实施注记：引擎参数唯一入口 `ModelInfo.to_engine_params()`；上游 `_verify_model` 对显式缺失路径直接抛 FileNotFoundError 本地错误，下载分支仅在未传路径时可达——死代理集成测试双重实证）

## 7. 构建与发布

- [x] 7.1 实现 `scripts/build.ps1`（清理 → `uv sync --frozen` → 测试 → PyInstaller → 复制 models/config → 创建 data/logs/cache）；验证从零执行可产出完整的 `dist/OCRTool/`（实施注记：构建前显式校验模型权重在场，缺失即报「请先运行 fetch_models.ps1」，不静默产出坏包）
- [x] 7.2 在构建脚本中加入产物结构断言：`models/` 与 `config/` 必须与 exe 平级、不得出现在 `_runtime/` 下；验证故意将 models 打入 `datas` 时该断言会失败（实施注记：断言独立为 `scripts/assert_dist.ps1`，负向验证以伪造 `_runtime/models` 产物树实证退出码 1）
- [x] 7.3 在构建脚本中加入禁止组件断言：产物内不存在 WebEngine / Multimedia / Qml / Quick / 3D / Charts 相关库文件；验证断言可执行且当前产物通过（负向以伪造 `Qt6WebEngineCore.dll` 实证退出码 1）
- [x] 7.4 实现 `scripts/release.ps1`（build → 冒烟验收 → 清理日志缓存与用户配置 → 打包 ZIP）；验证产出 `OCRTool-<version>-win-x64.zip` 且解压后 logs/cache/data 为空（实施注记：产出 165 MB ZIP，解压实测三个目录为空；压缩带 3 次重试以对抗杀软短暂锁定 exe）
- [x] 7.5 实现版本号单一来源与三处一致性（发布包名、启动日志、界面显示）；验证一致性测试通过（单一来源 `src/ocrtool/__init__.py`；三处消费 + pyproject 同步共 5 项测试守护；`--self-test` 为冒烟提供的无 UI 识别路径，正式 UI 随 mvp-image-ocr 落地后标题沿用 `window_title()`）
- [x] 7.6 将任务 1.6 的冒烟验收流程脚本化为发布强制关卡；验证冒烟失败时 `release.ps1` 以非零码退出且不产出 ZIP（实施注记：删除产物内 det.onnx 实证——冒烟报「无可用模型」退出码 1、dist 内零 ZIP；恢复模型后重跑发布成功。冒烟以死代理环境执行，同时复验零网络依赖）

## 8. 收尾

- [x] 8.1 回写 `OCRTool_桌面OCR开发设计书.md` 的 §8（双根路径）、§10（模型目录与 id）、§26（移除方向分类、线程配置映射）、§29（依赖侧断源机制）、§31（改为 spec 单一来源）、§45（升级策略简化）、§57（Python 3.13）；验证文档中不再残留 Python 3.11 与 `use_orientation` 字样（实施注记：连带修正文档头、§4.1 技术栈表、§7 `python311.dll`、§9.1 默认配置示例、§23.2 示例路径、§41 启动自检清单中的同源失效内容）
- [x] 8.2 编写 README 的开发环境搭建段落（`uv sync` + `fetch_models.ps1` 两步）；验证按文档在干净 checkout 上可从零跑到本地识别成功（实施注记：临时目录 `git clone` 后按 README 两步执行，死代理下 `--self-test` 输出 SELF-TEST OK、退出码 0）
- [x] 8.3 运行 `openspec validate --strict setup-project-baseline`；验证校验通过
