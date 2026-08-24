# model-switching 代码审查报告

## 审查元信息与结论

- **审查对象**：工作区未提交变更 vs HEAD（9abcff2）——model-switching（运行时模型切换）完整实现
- **变更范围**：`src/ocrtool/ocr/model_manager.py`（+14，`available_models` 枚举）、`src/ocrtool/ocr/service.py`（+60，`switch_model` 先构后换+失败回滚）、`src/ocrtool/ocr/worker.py`（+35，`ModelSwitchWorker`）、`src/ocrtool/ocr/states.py`（+4/−1，放开 LOADING→IDLE）、`src/ocrtool/controllers/ocr_controller.py`（+78，排队/互斥/接续）、`src/ocrtool/ui/main_window.py`（+84，模型菜单+结果标注）、`src/ocrtool/ui/widgets/status_widget.py`（docstring）、`src/ocrtool/ocr/result.py`（`model_name` 字段）、`packaging/models.lock.json`（ppocrv6-tiny 条目）+ 新增 `models/ppocrv6-tiny/model.json`（onnx 权重由 .gitignore 拦截不入库）、`tests/unit/test_model_switching_ui.py`（344 行 13 用例）、`tests/integration/test_model_switching_integration.py`（191 行 5 用例）+ 四处既有测试扩充；设计书 §12.1/§36 回写、tasks.md 21/21 勾选
- **方法**：变更摘要代理 + 5 并行审查代理（AGENTS.md 合规 / 浅层 bug / git 历史回归 / 既往审查适用性 / 注释指引）→ 汇总去重 4 个候选 → 逐问题独立验证评分（rubric 0/25/50/75/100，≥80 必须报告）→ 过滤
- **验证证据**：评分代理对 75/50 分项中 3 项做 offscreen 探针实测复现（75-1 成功/失败两场景、75-2 全链路、50-1 计数实证），50-2 三文件对照核实；审查代理各自运行相关测试子集通过（controller 8 用例 / service 7 用例 / UI 13 用例等）。未跑全量 pytest（本次为未提交变更审查，全量验证留待提交前）
- **结论**：**无 ≥80 置信度必须报告问题**。2 项 75 分（建议提交前修复，均为几行级）+ 2 项 50 分留档。变更整体质量高，可提交。

## 变更整体评价

- **「先构后换」回滚语义（design D1）——本变更最高风险面——实现正确**：`service.switch_model` 失败路径 `_engine/_model/_engine_params` 三者均不动（无半状态），旧引擎原封可用；成功路径三元组原子替换 + `del old_engine` 立即释放 + 重做 `silence_third_party_loggers()`（引擎初始化可能重挂第三方 handler，AGENTS.md 静默红线保持）。weakref 断言旧引擎被 GC 的测试在单测与集成（交替 20 轮后至多 1 个存活）双层覆盖；「det.onnx 截断为 64 字节」的真实损坏场景实测回滚可用。
- **排队互斥时序（D2/D3）自洽**：容量 1 线程池 + 控制器 busy 暂存 `_pending_switch` + `_finish_cycle` 接续（busy 全程不释放、token+1 作废残余回调）——git 历史审查逐点核对了 token 三个递增点与 mvp 75-3 防串图语义无冲突；10 轮交错回归、切换期间 5 次识别全被拒且事后 `recognize_calls == 0`（不堆积）、busy 信号单次翻转均有专测。
- **LOADING→IDLE 放开无借道**：`_transition(IDLE)` 全仓仅两处调用点（`_finish_cycle` 终态出边、`_finish_switch`），识别路径的 LOADING→ERROR 防御意图（2d736e6 初版「加载失败必须进错误态」）保持；状态机放宽的真正破坏面在 UI 驻留机制（见 75-1）。
- **AGENTS.md 红线逐条通过**：依赖未动；onnx 被 `.gitignore:251` 拦截（`git add -n` 干跑确认仅 model.json 入库）、lock 新条目 SHA256 与本地文件逐字符一致；切换走既有 `_engine_factory` 工厂路径无联网回退；分层完整（MainWindow→Controller→ModelSwitchWorker→Service，UI 未 import 引擎，业务层只消费 `OcrResult`）；切换日志只记 model_id/耗时，失败 QMessageBox 简短中文、技术细节随 detail/`logger.exception` 入日志；主线程 `aboutToShow` 重扫只读 model.json + 存在性（与启动自检同级，不加载 ONNX，惰性语义保持）。
- **D5 标注语义在成功/无结果/清空三条路径正确**，缺口仅在失败路径（见 75-2）；`model_name` 字段默认值与全部既有调用点（关键字调用）兼容。
- 既往审查教训未重犯：无信号双注册/程序性回环（QSignalBlocker 原则无适用面）、busy/token 守卫未绕过、UI 测试 fixture 显式 `auto_copy: False` 不写真实剪贴板、设计书回写与 lock 哈希登记齐整。
- tasks.md 21/21 勾选与交付吻合，唯 4.3 的断言覆盖窄于勾选声明（见 75-2 附带）。

## 75 分问题（建议提交前修复，均附修复方案）

### 75-1 每次模型切换完成后，状态区永久残留「正在加载模型…」

- **位置**：`src/ocrtool/controllers/ocr_controller.py:171-176`（`_finish_switch` 走 LOADING→IDLE，切换路径全程不经过任何有文本的终态）+ `src/ocrtool/ui/main_window.py:290-295`（`_on_state_changed` 对 IDLE 直接 return 不写文本）；`_on_model_switched`（:346-353）/`_on_model_switch_failed`（:355-357）均不触碰 `_state_label`
- **机制**：IDLE-跳过是为识别**终态**反馈驻留设计的（LOADING 后必经 RECOGNIZING→SUCCESS/EMPTY/ERROR，最后写入的必是终态文本）；本次新增的 LOADING→IDLE 切换路径使「正在加载模型…」成为最后写入且无人重置。对照 `status_widget.py:46-51` 既有注释「状态文本不在此清除……由调用方显式重置」——切换完成路径正是缺失的显式重置。
- **实证**：offscreen 探针——切换成功后 `state label='正在加载模型…'`、busy=False、switching=False、按钮已启用；失败场景（模拟关闭模态框）同样残留。对照组识别完成后 label='完成'，证明 IDLE-skip 驻留的是终态文本、切换路径驻留的是进行时文本，机制被误用。两个审查代理独立命中，评分代理复现。
- **影响**：模型切换是本变更核心功能，每次切换（无论成败）必现；按钮已恢复可用而状态区仍显示加载中自相矛盾；失败场景模态框说「仍在使用原模型」、状态区却显示「正在加载模型…」直接冲突。违反 `specs/ocr-execution/spec.md` 场景「切换完成后恢复：THEN 状态回到空闲」（与同 delta 前一场景的 UI 断言「状态区显示正在加载模型的提示」成对，此处「状态」最合理读法为状态区观感）。直到用户下次载图/识别/清空才消失。
- **修复方案**：`_on_model_switched`/`_on_model_switch_failed` 显式回落状态文本（如 `self._status.set_state("就绪")`），并补「切换成功/失败后状态区文本」两用例回归。

### 75-2 识别失败后切换模型，旧结果文本仍展示但模型段标注改为新模型（D5 破坏）

- **位置**：`src/ocrtool/ui/main_window.py:386`（`_on_error` 无条件 `_result_model_name = None`，但不清结果面板文本）+ `:351-352`（`_on_model_switched` 以 None 判定「无结果在展示」而 `set_model(新模型)`）；注释不变式在 `:62-63`（「None = 无结果在展示，状态区模型段此时跟随当前引擎模型」——失败路径下面板明明有文本，自相矛盾）
- **机制**：三代 `_on_error`（2d736e6→4c2a9e2→5d9a4f2）从不清结果面板文本，失败后旧结果保留展示是刻意历史行为；本次把锚点字段置 None 却保留文本，两头不占——状态区随后显示「模型B」而面板仍是模型 A 产出的文本。result-box-overlay 75-2/50-2「清除路径只清单侧」同款模式重现（`clear_all` 是文本与跟踪变量双侧清理，两条路径不对称）。
- **实证**：offscreen 全链路——模型 A 识别成功（label='模型A'、文本在）→ 再次识别失败（文本保留、tracked=None）→ 切换 B 成功 → label='模型B' 而面板仍是 A 的文本。三个审查代理独立命中，评分代理复现。
- **影响**：违反 main-window delta「切换后旧结果仍在展示……MUST NOT 让用户误以为结果来自新模型」（Requirement 主句以「当前展示的结果」为锚点，不限于成功后触发）与 design D5；「失败后换个模型再试」正是切换典型动机，此时耗时/行数已清、归属信息全部丢失。触发链「成功→失败→切换」三步组合，中低频但真实命中（模型文件损坏/图片解码失败同路径）。
- **测试缺口（附带）**：tasks.md 4.3 勾选声称「切换后旧结果保留且标注仍为旧模型（文本、框、耗时行数、模型标注全部保持）」，但 `TestResultModelLabel` 五个用例全在成功/无结果/清空路径，未测「识别失败（旧文本保留）后切换」——本缺陷正落在该未测路径。
- **修复方案**：失败路径与保留的旧文本自洽——`_on_error` 不再置 `_result_model_name = None`（保留旧结果归属），或改为连文本一起清（历史行为变更，需另行决策；推荐前者，与三代 `_on_error` 保留文本的行为一致）；补「失败后切换，标注停留旧模型」回归用例。

## 50 分问题（留档，可顺手修）

### 50-1 `_rebuild_model_menu` 每次重建累积 QActionGroup/QAction 不释放

- `src/ocrtool/ui/main_window.py:326`：每次菜单呈现新建 `QActionGroup(self._model_menu)`，`menu.clear()` 不删除 parent 为 group 的 action，旧 group 由 C++ 父链持有至窗口销毁。实证：重建 20 次后 20 group + 41 action（每次开菜单净增 3-4 个 QObject，<1KB），无功能影响、显示恒正确。与 screen-region-ocr 50-1 同构同档（修复提交 5018453 的 `deleteLater()` 模式：重建前对旧 group `deleteLater()` 或复用同一 group）。

### 50-2 `ModelSwitchWorker` docstring 互斥机制归因错误

- `src/ocrtool/ocr/worker.py:62-63`：「识别在途时本任务天然排队其后（design D2）」——实际 `ocr_controller.py:114-119` busy 时暂存 `_pending_switch` 不提交 worker、`:184-191` 识别结束后才提交，「池内排队」路径从未发生；且 design D2 原文只规定「等待不取消」的行为，未指定池排队机制，docstring 属自行演绎并误挂 D2 引用。纯注释错误无运行时影响，但若后续维护者据此把暂存改为直接提交，可能引入真 bug。修复：改写为「切换不与识别并发由控制器暂存 + 容量 1 池共同保证（design D2 的等待语义由控制器实现）」，顺带修正 `ocr_controller.py:9` 模块 docstring 同款措辞。

## 留档备注（不计问题）

1. UI 直接调 `model_manager.available_models()` 而非经 Controller 转发（`main_window.py:316-320`）——合规判定：model_manager 是目录枚举/元数据模块非引擎，且沿用既有 `_run_startup_self_check` 调 `resolve_model` 的同一模式，不判违反 AGENTS.md「UI 禁止直接调用 OCR 引擎」；若后续想收紧「UI 只经 Controller」边界，可作重构议题。
2. 防御性弱点（不可触达）：`_on_switched`/`_on_switch_failed` 的 token 过期分支直接 return 会永久卡 busy/switching——但正常时序下不存在能在切换在途期间改 token 的调用方（识别被 busy 挡、切换被 switching 挡），无法构造触发路径，留档备查。
3. 集成测试 `TestRealSwitching` 的 RSS 内存断言因 onnxruntime 内存池归还策略改为 weakref 存活数参考——处理得当，tasks.md 已说明理由。
4. `load_from_clipboard` 无 busy 守卫等既往留档项本次未触碰、未扩大，维持归后续变更。

## 提交建议

- 变更整体质量高、无阻塞问题，可直接 `ADD:` 提交（model-switching 实现与规划件一并）。
- 75 分两项建议提交前顺手修（75-1 两处补状态回落、75-2 一行改判定+补回归；合计约 5 行代码 + 3 个用例），或先提交、修复另起一笔 `FIX:` 提交（沿用 mvp/screen-region/result-box 先例，修复后在本文档追加修复落地记录）。
- 50-1/50-2 可随 75 分修复同批顺手处理（各一行级）。
- 两个 75 分项集中在「切换完成后的 UI 状态收尾」，与五层核心实现（枚举/切换回滚/池任务/排队互斥/菜单入口）质量无关——核心路径的测试密度与实证质量是本变更亮点。

## 修复落地记录（2026-08-24）

实施流程：先 `ADD:` 提交变更本体（e3dec64，19 文件 +1375/−66），后按红绿流程修复（探针复现 → 4 个红用例 → 修复转绿 → 全量回归），另起 `FIX:` 提交。

| 项 | 修复 | 验证（红 → 绿） |
|---|---|---|
| 75-1 状态区残留「正在加载模型…」 | `_on_model_switched`/`_on_model_switch_failed` 显式 `set_state(STATE_TEXTS[OcrState.IDLE])`（IDLE-跳过驻留机制为识别终态设计，切换路径必须自行收尾） | 新增 `TestSwitchCompletionState` 两用例：切换成功/失败后 label 断言「就绪」。红：两用例均以 label=='正在加载模型…' 失败；绿：均通过 |
| 75-2 失败后切换标注错配 | `_on_error` 删除 `_result_model_name = None`——旧结果文本按三代既有行为保留展示，归属标注随之保留（采纳报告推荐方案 A；方案 B 清文本会改变历史行为，未取） | 新增「识别失败后切换_旧文本与标注均保持旧模型」用例（成功→失败→切换→重识别四步）。红：失败于切换后 label=='模型：模型B'（探针预测点）；绿：标注停留「模型A」，重识别后才更新 |
| 50-1 QActionGroup 累积 | `_model_group` 存为窗口属性，`_rebuild_model_menu` 重建前对旧 group `deleteLater()`（screen-region 5018453 同款模式） | 新增「菜单重建不累积QActionGroup」用例。红：重建 20 次后 20 个 group；绿：恰 1 个。**实施注记**：DeferredDelete 不随 `processEvents()` 派发（Qt 仅在运行中的事件循环处理），测试须显式 `sendPostedEvents(None, QEvent.DeferredDelete)`；生产环境 `app.exec()` 下 deleteLater 自然生效，代码无需特殊处理 |
| 50-2 docstring 归因错误 | `worker.py` ModelSwitchWorker 与 `controller.py` 模块头改写为「控制器暂存 + 容量 1 池兜底」的准确归因；**额外发现**：`tasks.md` 2.3 注记存在同源错误表述（「在途识别天然先执行完」），一并修正（报告未列，评估阶段核实发现） | 三文件 grep 确认无「天然排队」残留表述；无运行时影响 |

修复未引入新问题：全量 323 passed（319 + 4 新回归用例），改动文件 ruff 全净；`openspec validate --strict model-switching` 通过。
