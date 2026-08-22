# mvp-image-ocr 代码审查报告

## 审查元信息

- **日期**：2026-08-22
- **审查对象**：工作区对 `HEAD(8820bfa)` 的全部未提交变更——mvp-image-ocr 完整实现（6 个已跟踪文件修改 + 40 个未跟踪新文件，约 +3955 行：`src/ocrtool/` 下 app/controllers/ocr/ui/utils 新模块、`tests/` 全套、`scripts/dev_e2e_ocr.py`、设计书与 tasks.md 回写）
- **对照基线**：`openspec/changes/mvp-image-ocr/`（proposal/design/specs/tasks）+ 归档主规范 `openspec/specs/` + AGENTS.md 红线
- **方法**：5 个并行代理独立审查（AGENTS.md 合规 / 浅层 bug 扫描 / git 历史上下文 / 既往评审意见适用性 / 代码注释指引），汇总去重得 12 个候选问题，每个问题由独立评分代理按 0–100 置信度复核（两项经 PySide6 6.11.2 offscreen 实测验证）
- **门槛**：≥80 分计入必须报告项

## 审查结论

**发现 1 项必须报告问题（100 分）：Ctrl+V 快捷键双重注册导致粘贴快捷键完全失效。**

**75 分及以下共 9 项，均低于门槛，不构成阻塞**，分档列于下文供顺手修复。

## 变更整体评价

实现质量高。39/39 任务勾选且有实测证据；AGENTS.md 红线逐条核对全部通过（分层边界——UI 层零 RapidOCR 引用、业务层只消费 `OcrResult`；惰性加载 + 启动 `assert not service.engine_loaded`；token 防串图 + busy 拒绝重入；日志隐私——新模块只记尺寸/行数/耗时/异常，第三方 logger 三处静默；全内存无落盘——grep 无临时文件写入；禁网引擎参数——显式本地路径 + `use_cls=False`）。上轮 review.md 留档的两项 UI 接线欠账（配置警告、模型缺失提示）本变更已完整还清。审查代理实测验证通过的高风险点：QImage→ndarray 复制无悬垂、坐标 scale 全链路透传、`RapidOCROutput` None 字段全兜底、QRunnable 跨线程信号经主线程代理、状态机六态全路径合法、退出时 QThreadPool 析构自动 waitForDone 不崩溃（原推测性担忧被实测否定）。

## 分档问题

### 100 分（必须报告）

**1. Ctrl+V 双重注册：粘贴快捷键完全失效（ambiguous overload），且 busy 期独立 QShortcut 绕过禁用**

- 位置：`src/ocrtool/ui/main_window.py:92-95`（`_paste_action.setShortcut(QKeySequence.StandardKey.Paste)`，经 `addAction` 以 WindowShortcut 作用域生效）与 `src/ocrtool/ui/main_window.py:110-112`（独立 `QShortcut(QKeySequence("Ctrl+V"), self).activated.connect(self.load_from_clipboard)`）
- 机制：同一键序列在同一窗口作用域注册两次，Qt 快捷键消歧判定为 ambiguous overload——按下时**两条都不激活**，`load_from_clipboard` 调用 0 次。评分代理已在仓库 .venv（PySide6 6.11.2，offscreen，QTest 真实按键）实测复现：双注册时触发 0 次，仅保留 action 时正常触发 1 次。`tests/unit/test_main_window.py` 无按键级测试，现有套件无法暴露。
- 附带影响：`_update_actions`（`main_window.py:198-206`）busy 期禁用的是 `_paste_action`，独立 QShortcut 不受 QAction 禁用影响，Ctrl+V 在识别中仍可载入新图（与 75-2 拖放问题同源）。
- 修复：删除独立 `QShortcut`（约 110-112 行），`_paste_action` 的 `StandardKey.Paste` 已完整覆盖该快捷键；补一条按键级回归测试（QTest.keyClick 断言 `load_from_clipboard` 恰好调用一次）。

### 75 分（建议顺手修复）

**2. GUI 启动顺序颠倒：先加载配置后初始化日志，配置异常日志不落盘**

- 位置：`src/ocrtool/app/application.py:34-36`（`bootstrap()` 实际顺序 路径 → 配置 → 日志）；与 `application.py:3-4`、`src/ocrtool/main.py:3-4` 两处 docstring 声明的「路径 → 日志 → 配置」相反
- 机制：`config/manager.py` 的 `load()` 在加载过程中用 `logging.getLogger("ocrtool.config")` 记录错误（默认配置缺失/解析失败、用户配置损坏），该日志依赖 `setup_logging()` 挂载的 RotatingFileHandler；GUI 路径下 `load_config` 先执行，错误只走 lastResort→stderr，不写入 `ocrtool.log`。评分代理已在临时目录实测：GUI 顺序下损坏配置的 logger.error 不落盘，`--self-test` 路径（先日志后配置）正常落盘。违反 `openspec/specs/app-config/spec.md:22-23、45-47` 两个「记录一条错误日志」scenario；git 证据：`131519b` 起 GUI 走 `_startup()`（先日志后配置），本次重构引入回归。
- 修复：`bootstrap()` 改为先 `setup_logging()`（默认级初装）再 `load_config()`，拿到配置后再 `setup_logging(level=...)` 重挂——与 `main.py` `_startup()` 同模式；顺带修正两处 docstring 与实际一致。

**3. 识别期间拖放入口未禁用，旧图识别结果会配到新图上（串图）**

- 位置：`src/ocrtool/ui/widgets/image_viewer.py:97-114`（拖放始终接受）→ `src/ocrtool/ui/main_window.py:114`（`imageDropped` 直连）→ `main_window.py:153-160`（`load_from_path` 无 busy 守卫）
- 机制：识别进行中拖入新图会替换 `_pending_image`/预览；旧图识别结果到达时 token 未变（token 仅在 `start_recognition` 递增），结果照常展示——用户看到新图配旧图文本，正是 token 机制要防的串图在「换图不识别」路径上的绕过。违反 `openspec/changes/mvp-image-ocr/specs/ocr-execution/spec.md`「任意一次识别结果被展示 THEN 对应当前预览图像」；`design.md` D3 明言「第一版界面禁用（入口）可以避免串图」。open/paste/clear 均已随 busy 禁用，唯拖放（与 100-1 的独立 Ctrl+V）漏禁，属疏漏非有意设计。
- 修复：`load_from_path` 入口加 busy 守卫直接忽略（返回 False 或仅状态提示），或 busy 期 `viewer.setEnabled(False)`；与 100-1 一并处理可覆盖全部绕过路径。

### 50 分（低优先级）

**4. UI 初始化异常的日志防护被重构删除未迁移**：HEAD `main.py` 原有 `except Exception: logger.exception("启动失败…")`（`131519b` 引入），迁移到 `application.py:79-81` 后无等价防护，UI 组装异常退化为无日志直接崩溃。减轻：打包 `console=True`，traceback 仍上 stderr。修复：`run()` 内 UI 组装段补 try/except + `logger.exception`。

**5. 过期 token 分支释放错误 worker**：`controllers/ocr_controller.py:94-97、105-108` 的过期分支调用 `_release_worker()` 会置空 `_active_worker`——而 token 变化意味着新请求已把 `_active_worker` 指向新 worker，释放的恰是新 worker 的唯一 Python 锚点，与 `ocr_controller.py:44-47` 注释声明的生命周期规则自相矛盾（对照 `_on_loaded` 过期分支 90-91 行不释放）。busy 门控 + 单次终止信号使该分支生产不可达（仅测试靠篡改 `_token` 触达），属防御死代码中的瑕疵。修复：过期分支改为「不释放、直接 return」（与 `_on_loaded` 对齐）。

**6. dev_e2e_ocr.py 无 UTF-8 输出流防护**：`scripts/dev_e2e_ocr.py:40,51-53` 打印中文与 OCR 文本，非 CJK 代码页机器重定向运行会 `UnicodeEncodeError`（上轮 review 3.1 同模式，`main.py:70-77` 的 `_force_utf8_stdio()` 现成未复用）。减轻：无自动重定向调用方，需手动重定向 + 非 CJK 代码页双条件。修复：脚本入口加同样两行 reconfigure。

**7. 设计书 §20/§9.1 配置示例与 `ocr.max_edge_px` 键名漂移**：`OCRTool_桌面OCR开发设计书.md:1245`（§20 示例 `image.max_dimension`）与 `:505`（§9.1 ocr 段缺 `max_edge_px`）落后于实现（`config/default.json:4`、`defaults.py:13`、`main_window.py:55` 均为 `ocr.max_edge_px`）。上轮 4.2 同类。修复：两处示例改为实际键名。

**8. 错误呈现分级：spec 冲突未消解**：mvp delta spec `main-window/spec.md:68`「配置损坏 THEN 弹出对话框」与归档主规范 `app-config/spec.md:47`「在界面状态区提示」两个 MUST 句直接冲突，实现选了后者（可辩护）；RecognitionError 走状态栏而非 QMessageBox，属 delta spec 未归类的缺口（AGENTS.md 字面 vs `design.md` 反弹窗理念）。修复：归档本变更前在 delta spec 中消解措辞（建议按实现口径收紧），不改代码。

**9. service.py「唯一持有 RapidOCR 实例」docstring 与现状矛盾**：`ocr/service.py:1` 的绝对表述 vs `main.py:91-100` `run_self_test` 自建实例消费原生输出（HEAD 旧账，本次未改）。修复：docstring 收窄为「GUI 识别路径唯一持有」或将自检迁移到服务层（归后续变更）。

### 25 分（留档）

**10. InvalidImageError message 含文件名/扩展名**：`utils/image.py:33,40` 把 `path.suffix`/`path.name` 写入 message 并经 `main_window.py:158` 显示状态栏，字面突破 `exceptions.py:3-4`「路径绝不进入界面文本」。裁定为 docstring 措辞过严（权威 spec 仅禁调用栈/原始异常，文件名是用户已知信息）。修复：放宽 docstring 措辞为「完整路径与调用栈」即可。

### 已实测否定（0 分，不计问题）

- **识别中关窗退出崩溃**：推测不成立。QThreadPool 析构自动 `waitForDone()`（实测慢 worker + 关窗：进程等待 worker 完成后 EXIT_CODE=0 退出，不崩）；`design.md` 明确「不实现真正中断」。
- **GUI 入口 stderr 中文编码**：HEAD 的 GUI 分支（`main.py` 旧 `_startup` 路径）同样无防护，属预存在问题非本变更引入；且需路径解析失败 + stderr 重定向 + 非 CJK 代码页三重叠加。

## 留档备注（归后续变更）

- `main.py` `run_self_test` 直接持有 RapidOCR 实例、绕过服务层单点适配（HEAD 旧账）——若 RapidOCR 升级破坏 API，自检路径无防护；建议后续变更迁移至 `OCRService`。
- `tests/unit/test_main_window.py` 缺按键级测试（100-1 因此漏网）；补快捷键回归测试可随修复一并落地。
- `bootstrap()` 与 `_run_startup_self_check` 各调一次 `resolve_model`，模型异常时错误日志重复两遍——冗余无害，可顺手收敛。

## 提交建议

1. **先修 100-1（Ctrl+V 失效）再提交**——核心输入方式每次必失效，属必须修复；顺带补按键级回归测试。
2. 建议 75-2（启动顺序）、75-3（拖放串图）随本次一并修复（均为小改动：一处顺序调整 + 一个 busy 守卫），修复以 `FIX:` 提交或在实现提交前直接改入。
3. 其余 50/25 分项可留待后续；8 号（spec 冲突）须在本变更归档前于 delta spec 消解。
4. 实现本体以 `ADD:` 提交（含本 review.md），随后走 openspec-archive-change 归档流程。

## 修复落地记录（2026-08-22）

按上述建议全部落地（10/10，含 25 分项），三笔提交：

| 提交 | 内容 | 验证 |
|---|---|---|
| `ADD`（实现本体） | mvp-image-ocr 完整实现 + 本 review.md，46 文件 | 192 测试通过（提交时点） |
| `FIX` 第一笔 | **100-1**：删除独立 QShortcut；**75-2**：bootstrap 先 `setup_logging()` 再 `load_config()` 再按配置重挂；**75-3**：`load_from_path` 加 busy 守卫（识别中忽略载入并状态提示） | 红-绿实证：三个新回归测试在未修复代码上全部失败（Ctrl+V 双注册 0 次触发、busy 换图串图、损坏配置日志只走 stderr），修复后通过；另以独立对照实验证实双注册下 action 与 QShortcut 均 0 次触发 |
| `FIX` 第二笔 | **50-4**：`run()` UI 组装段补 try/except + `logger.exception`；**50-5**：过期分支不再 `_release_worker`（与新 worker 锚点冲突）；**50-6**：`dev_e2e_ocr.py` 入口 reconfigure UTF-8；**50-7**：设计书 §20/§9.1 键名改 `ocr.max_edge_px`；**50-8**：delta spec「需要用户介入的错误」移除「配置损坏」，注明遵循 app-config 主规范（状态区提示）——归档前冲突已消解；**50-9**：`service.py` docstring 收窄为「GUI 识别路径唯一持有」；**25-10**：`exceptions.py` docstring 放宽为「完整路径不进界面」 | 全量 195 测试通过（+3 回归）；`openspec validate --strict mvp-image-ocr` 通过 |

留档备注三项维持不动（run_self_test 绕过服务层、按键级测试已随 100-1 补上、resolve_model 双调冗余），归后续变更。
