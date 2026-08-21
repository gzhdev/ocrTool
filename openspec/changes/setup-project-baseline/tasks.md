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

- [ ] 2.1 补全 `pyproject.toml` 的项目元数据、`src` 布局配置与开发依赖（pytest）；验证 `uv sync --frozen` 成功
- [ ] 2.2 提交 `uv.lock`；验证在另一份干净 checkout 上 `uv sync --frozen` 可复现完全相同的依赖版本
- [ ] 2.3 在 `.gitignore` 中排除 `models/**/*.onnx` 并显式保留 `models/**/model.json`；验证 `git status` 中模型权重不出现、`model.json` 出现
- [ ] 2.4 添加依赖约束的回归检查（脚本或测试）：断言已解析依赖中不含 `pyside6-addons` 与非 headless 的 `opencv-python`；验证该检查在故意还原依赖时会失败

## 3. 路径与存储模式

- [ ] 3.1 实现 `app/paths.py` 的双根解析（`APP_ROOT` / `USER_ROOT`）与开发/打包环境判别；验证单元测试覆盖两种环境下的根目录取值
- [ ] 3.2 实现基于实际写入的可写性探针（含探测后清理）；验证单元测试模拟可写与不可写两种情形，且确认未使用 `os.access`
- [ ] 3.3 实现 `OCRTOOL_DATA_DIR` 覆盖，无效时以明确原因终止启动；验证单元测试覆盖「有效覆盖」「无效覆盖导致启动失败」两个场景
- [ ] 3.4 实现可写目录的按需创建；验证首次运行后 `data` / `logs` / `cache` 目录存在
- [ ] 3.5 添加「不依赖当前工作目录」的集成测试：从其他磁盘目录启动进程；验证路径解析结果与从程序目录启动时一致

## 4. 日志

- [ ] 4.1 实现 `utils/logger.py`：日志落 `USER_ROOT/logs`、5 MB × 3 轮转、级别可配；验证单元测试确认轮转触发与文件数量上限
- [ ] 4.2 实现启动环境信息记录（版本、OS、运行时、provider、线程数、存储模式、`USER_ROOT` 实际路径）；验证启动后日志首段包含全部字段
- [ ] 4.3 实现第三方 OCR 组件 logger 的接管（清空 handler、断开传播）；验证集成测试执行一次识别后，日志与标准输出中均不含识别文本
- [ ] 4.4 添加隐私回归测试：在 DEBUG 级别下执行识别；验证日志仅含尺寸、行数、耗时，不含任何识别文本
- [ ] 4.5 确认日志初始化发生在路径探测之后；验证启动期人为制造异常时，该异常能被写入最终日志文件

## 5. 配置

- [ ] 5.1 定义内置默认值与 `config/default.json`（不含方向分类开关）；验证两者字段集合一致的测试通过
- [ ] 5.2 实现三层优先级合并与首次运行生成用户配置；验证单元测试覆盖三层各自缺失时的回落行为
- [ ] 5.3 实现配置损坏降级：备份损坏文件、以默认值启动、记录错误；验证注入非法 JSON 后程序仍能启动且备份文件存在
- [ ] 5.4 实现写回时保留未识别字段；验证单元测试确认额外字段在读写往返后仍然存在
- [ ] 5.5 添加升级不覆盖用户配置的集成测试：模拟替换程序目录后启动；验证用户配置项依然生效

## 6. 模型资产

- [ ] 6.1 定义 `model.json` 结构（含 `id` / 模型文件名 / `languages` 语义修正 / `recommended`）并为 `ppocrv6-small` 落地一份；验证结构校验测试通过
- [ ] 6.2 实现模型目录扫描与完整性校验（缺文件、id 重复的处理）；验证单元测试覆盖完整、缺文件、id 重复三种情形
- [ ] 6.3 实现模型解析回退链（配置 id → recommended → 首个 → 自检失败）；验证单元测试逐级覆盖四个分支
- [ ] 6.4 编写 `packaging/models.lock.json`，SHA256 取自 rapidocr 上游 `default_models.yaml`；验证登记的哈希与实际文件一致
- [ ] 6.5 实现 `scripts/fetch_models.ps1`（幂等、校验、失败即删）；验证连续执行两次第二次全部跳过，且篡改文件后重跑会删除并报错
- [ ] 6.6 确认引擎调用始终显式传入本地模型路径且关闭方向分类；验证断网环境下识别成功，且模型缺失时报本地路径错误而非发起下载

## 7. 构建与发布

- [ ] 7.1 实现 `scripts/build.ps1`（清理 → `uv sync --frozen` → 测试 → PyInstaller → 复制 models/config → 创建 data/logs/cache）；验证从零执行可产出完整的 `dist/OCRTool/`
- [ ] 7.2 在构建脚本中加入产物结构断言：`models/` 与 `config/` 必须与 exe 平级、不得出现在 `_runtime/` 下；验证故意将 models 打入 `datas` 时该断言会失败
- [ ] 7.3 在构建脚本中加入禁止组件断言：产物内不存在 WebEngine / Multimedia / Qml / Quick / 3D / Charts 相关库文件；验证断言可执行且当前产物通过
- [ ] 7.4 实现 `scripts/release.ps1`（build → 冒烟验收 → 清理日志缓存与用户配置 → 打包 ZIP）；验证产出 `OCRTool-<version>-win-x64.zip` 且解压后 logs/cache/data 为空
- [ ] 7.5 实现版本号单一来源与三处一致性（发布包名、启动日志、界面显示）；验证一致性测试通过
- [ ] 7.6 将任务 1.6 的冒烟验收流程脚本化为发布强制关卡；验证冒烟失败时 `release.ps1` 以非零码退出且不产出 ZIP

## 8. 收尾

- [ ] 8.1 回写 `OCRTool_桌面OCR开发设计书.md` 的 §8（双根路径）、§10（模型目录与 id）、§26（移除方向分类、线程配置映射）、§29（依赖侧断源机制）、§31（改为 spec 单一来源）、§45（升级策略简化）、§57（Python 3.13）；验证文档中不再残留 Python 3.11 与 `use_orientation` 字样
- [ ] 8.2 编写 README 的开发环境搭建段落（`uv sync` + `fetch_models.ps1` 两步）；验证按文档在干净 checkout 上可从零跑到本地识别成功
- [ ] 8.3 运行 `openspec validate --strict setup-project-baseline`；验证校验通过
