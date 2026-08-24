# screen-region-ocr 代码审查报告

## 审查元信息

- **日期**：2026-08-22
- **对象**：未提交工作区改动（基线 HEAD=150e005），实现 OpenSpec 变更 `screen-region-ocr`。范围：修改 7 文件（设计书、config/default.json、defaults.py、main_window.py、clipboard.py、image.py、qt_helpers.py）+ 新增 `src/ocrtool/capture/`（region_overlay.py 277 行、screen_capture.py 146 行、`__init__.py`）+ 新增 4 个测试文件（804 行）+ 本变更全部规划件。工作区另有三个**纯提案**变更目录（background-residency、model-switching、result-box-overlay，均 0 任务勾选、无实现），不属本次实现审查范围。
- **方法**：摘要代理 + 5 个并行独立审查代理（AGENTS.md 合规 / 浅层 bug / git 历史回归 / 既往审查意见适用性 / 代码注释指引）→ 汇总去重 10 个候选 → 10 个并行评分代理独立验证打分（含 offscreen 合成双屏全链路复现、真实键盘注入、变异测试）。
- **门槛**：0–100 置信度，≥80 计入必须报告项。
- **实跑证据**：全量 `uv run pytest -q` = **239 passed**（73.39s）；`openspec validate --strict screen-region-ocr` = valid；评分代理实证 Ctrl+Shift+S 真实按键恰好触发 1 次、选区期间主窗口隐藏期 Ctrl+V/Ctrl+O 按键 0 次触发。

## 审查结论

**1 项 ≥80 必须报告**：副屏/非原点屏选区坐标双重平移（100 分，三代理独立发现、两轮独立复现，违反本变更两条核心 spec MUST）。**当前状态不建议直接提交**，先修 100-1（连带补副屏端到端测试），75-1 建议顺手同批修复。

## 变更整体评价

- **任务完成度**：tasks.md 35/35 全勾，与交付吻合；新增 44 个测试。
- **AGENTS.md 红线逐条全过**：无新增第三方依赖（仅 PySide6 essentials，未引入 QtMultimedia，符合 design D3）；全程纯内存零临时文件（有专项测试锁定）；日志只记屏幕名/几何/缩放/尺寸/耗时/异常（无 OCR 文本与图像内容）；分层未破坏（capture 包不接触引擎，识别仍走 Controller→Worker→Service）；token 防串图复用且截图路径换图后立即识别使 token 及时递增；无 print/无 stdout 中文输出风险。
- **既往审查模式**：6 类问题模式中 5 类未复发/不适用（Ctrl+V 双注册、启动顺序、换图串图、worker 锚定、stdout 编码均实证通过）；按键级测试缺口在新快捷键上部分复发（50-3）。
- **规划件质量**：design D1–D7 决策清晰，spec 与实现基本逐条对上（自动复制 5 个 Scenario 全过）；但**决策关卡 1.6 的验证方法存在系统性盲区**——`QT_SCALE_FACTOR` 单屏实测（屏原点恒为 (0,0)）+ 纯函数级单测（按全局坐标传参），恰好都测不到「屏原点偏移 × overlay 局部坐标」的组合，这正是 100-1 漏网的直接原因，也是 proposal.md 自认首要风险（混合 DPI/多屏错位）「单显示器开发机上永远无法暴露」的注脚。

## 分档问题

### 100-1【必须报告】副屏选区坐标双重平移——任何非原点屏上截图永远静默取消或裁错区域

- **位置**：
  - `src/ocrtool/capture/region_overlay.py:127,143-152`——选区用 `event.position().toPoint()` 构造并经 `selectionDone` 发出，这是 **overlay 局部逻辑坐标**（overlay `setGeometry(snapshot.geometry)`，局部原点=该屏左上角；`:40` 信号注释「已夹取在本屏内」亦证明）；`:91` 尺寸提示与 `:147-151` 面积过小判定同用此坐标。
  - `src/ocrtool/capture/screen_capture.py:114-120`——`logical_to_physical` 契约为**全局逻辑坐标**（docstring 明示，第一步 `rect.translated(-snapshot.geometry.topLeft())`；`tests/unit/test_screen_capture.py:59-66` 也按全局坐标测试）。
  - 断链点：`region_overlay.py:225-227` lambda 把局部 rect 原样透传 `_on_selection_done → crop_snapshot`，中间无任何平移。
- **机制**：两模块坐标语义不匹配，仅 `geometry.topLeft()==(0,0)` 的屏恰好等价。副屏上局部坐标被再减一次屏原点 → 平移到屏外 → `intersected` 为空 → `physical_size_of` 返回 0×0 → 落入「面积过小」取消分支，**静默取消**；平移后仍有部分交集时则**裁出错位区域**（偏移量=屏原点×DPR）。
- **实证**（评分代理，offscreen 合成双屏 主屏(0,0,640,480)+副屏(640,0,800,600)，注入快照、走 RegionOverlay 真实鼠标事件全链路）：主屏对照组 `('finished', 301, 201, 正确颜色)`；副屏左半同样 301×201 有效选区 → `('cancelled',)`；副屏右半（框选蓝色区）→ `('finished', 100, 201, 红色)`——内容左偏 640px 的错误区域。常见等宽双屏下副屏局部 x 恒小于主屏宽，**任何选区都会被取消**。
- **违反 spec**（specs/screen-capture/spec.md）：`:43-45`「在副屏发起选区…得到的图像内容与该副显示器上被框选的区域一致」、`:51-53`「多块屏幕缩放比例不同…不发生偏移或错位」，均为 MUST Scenario；而 proposal.md 第 7–12 行自认混合 DPI/多屏错位是本变更**首要风险**。
- **测试盲区**：全部流程测试快照均为 (0,0) 原点（test_region_overlay.py:26、test_capture_flow.py:18、test_capture_entry.py:82）；test_capture_flow.py:162-178 构造了 (640,0) 副屏但只测「全部关闭」，从未在其上框选。
- **修复方向**（二选一，并补一个非原点屏的「框选→裁剪→内容」端到端测试）：
  1. overlay 在 emit 与 `physical_size_of` 调用前把选区 `translated(snapshot.geometry.topLeft())` 转为全局逻辑坐标（此方向下 `snapshot_at`（screen_capture.py:106-111）复活可用，见 50-7）；
  2. 把 `logical_to_physical`/`crop_snapshot` 契约改为接收屏内局部坐标（去掉 translated），同步改 docstring 与既有函数级测试。

### 75-1【建议顺手修复】Alt+F4 绕过全部三条结束路径——应用僵尸化，主窗口永不恢复

- **位置**：`src/ocrtool/capture/region_overlay.py:37-158`（RegionOverlay 只处理鼠标/ESC/右键，无 `closeEvent`/`destroyed` 处理）；`src/ocrtool/ui/main_window.py:201-202`（重入守卫完全依赖 `active`）。
- **机制与实证**（评分代理四层实测，含 Windows 真实键盘注入）：选区期间覆盖层是前台窗口，Alt+F4 发送 WM_CLOSE 不受 frameless/无 WS_SYSMENU 阻挡（`keybd_event` 注入实证 closeEvent 收到）。而 `Qt::Tool` 窗口默认 `WA_QuitOnClose=False`，**不会**触发应用退出——真实后果比「静默退出」更糟：覆盖层被关闭但 flow 三条信号（finished/cancelled/failed）全不发射，`flow.active` 恒 True → 截图入口永久拒绝、主窗口保持隐藏、无任何可见窗口，**只能任务管理器强杀**。单屏/多屏结论相同。
- **违反**：spec「以任意方式结束…主窗口恢复到发起前的可见状态」（spec.md:19-21）；design.md D6「任何一条被遗漏的路径……值得用结构保证而非纪律保证」——closeEvent 正是 D6 要堵的那类路径。
- **修复**：RegionOverlay 覆盖 `closeEvent` 转 `cancelled.emit()`（`_ended` 防重入与 `_on_cancelled` 守卫已保证无递归风险），或 flow 监听覆盖层 `destroyed`。
- **为何 75 非 100**：机制确凿但触发低频（用户需在选区期间按 Alt+F4）。

### 50-1 RegionCaptureFlow 对象累积不释放

`main_window.py:205` 每次截图新建 flow（parent=MainWindow）并替换 `self._capture_flow`，旧 flow 结束后无 `deleteLater`，由 C++ 父链持有至主窗口销毁，3 个信号连接随行（region_overlay.py:172-178、266-277 只销毁覆盖层）。每次累积 <1KB、无功能影响（`_ended` 已惰性化）。修复一行：`_on_capture_finished/_on_cancelled` 等结束回调后 `flow.deleteLater()`，或 flow 结束时自毁。注：「每次新实例」是 tasks.md 3.7 的设计决定，本项只缺「结束后销毁」这最后一步。

### 50-2 _show_overlays 中 show() 先于入列表——覆盖层残留的结构性缺口

`region_overlay.py:229-230`：`overlay.show()` 在 `self._overlays.append(overlay)` 之前。若 show() 抛异常，`_abort→_cleanup` 只能销毁列表内的覆盖层，这块已显示的全屏置顶窗口永久残留（违反 spec「选区界面 MUST NOT 在任何结束路径上把覆盖层留在屏幕上」）。PySide6 中 show() 可传播 Python 异常的机制面几乎为零（Qt C++ 不用异常；回调异常被 Shiboken 吞掉），故实际命中概率≈0，但修复是纯换序零成本，与 D6「结构保证」立论一致：**把 append 移到 show() 之前**。

### 50-3 Ctrl+Shift+S 缺按键级回归测试（既往教训部分复发）

新快捷键无按键级用例（test_capture_entry.py:89-95 直调方法、:97-102 仅断言 isEnabled；4 个新文件唯一 keyClick 是 test_region_overlay.py:77 的 ESC）。mvp 审查 100 分 bug（Ctrl+V 双注册）正是从该缺口漏网，修复时补过 Ctrl+V 按键级回归（test_main_window.py:409-437）。当前代码已实证健康（QTest.keyClick 恰好触发 1 次），属防护缺口。修复：仿 Ctrl+V 用例补 `QTest.keyClick(win, Key_S, Control|Shift)` 断言恰好 1 次（0 次=ambiguous、>1=重复注册）。

### 50-4 主窗口「发起前可见性」记录存在窗口期

`region_overlay.py:193` 在 `_hide_and_wait` 返回后才写 `_window_was_visible`，而 `:207` 的 `window.hide()` 副作用先发生；若其间抛异常，`_cleanup`（`:274`）读到初始值 False 不恢复主窗。评分代理实测 PySide6 的 `processEvents()` 不传播槽异常（Shiboken 吞掉），循环体（:211-217）其余调用无现实异常源，窗口期实际不可达。修复：hide 前先记录 `was_visible`（或拆「记录」与「隐藏等待」两步）。

### 50-5 测试 fixture 配置契约失真——默认场景自动复制测试恒真

`tests/unit/test_capture_entry.py:55-59` window fixture 传普通 dict，而实现读点路径 `self._config.get("ui.auto_copy", True)`（main_window.py:269）；普通 dict 的点路径 key 恒 miss 恒返回默认 → `test_默认开启成功检出文本自动复制`（:200-207）即使 key 写错也通过（变异测试实证：改成 `ui.autocopy` 后该用例仍绿）。同文件 ：183-196 已有 DottedDict 替身却只用于 2 个用例。关闭场景（:238-256）能兜住 key 写错，故防御深度从 2 降为 1 而非归零。修复：fixture 统一 DottedDict。

### 50-6 delta spec「三种输入」标题与「四种输入」正文名实不符（归档时处理）

specs/image-input/spec.md:3-5 MODIFIED Requirement 标题保留主规范旧名「支持三种图像输入方式」（OpenSpec 按标题匹配的机制要求，validate --strict 通过，非违规），但归档同步后主规范将永久「标题三种/正文四种」。处理：归档时补 RENAMED（FROM 旧名 TO「支持四种图像输入方式」）或在归档说明中明确；本仓库 sync/archive skills 已支持 RENAMED 但变更内无此安排。

### 50-7 snapshot_at 生产零引用（死代码，处置与 100-1 修复方向耦合）

`screen_capture.py:106-111`（按全局逻辑点寻屏）仅被单测引用；生产链路用 lambda 逐屏捕获 snapshot 替代。它是「overlay 发全局坐标」原始设计的遗迹——若 100-1 按方向 1 修复则复活有用，按方向 2 修复则应删除。随 100-1 一并处置。

### 25-1 _on_capture_finished 无异常防护（沿袭既有模式，非本次引入的风格）

`main_window.py:212-223` 的 `qimage_to_bgr/scale_to_limit` 无 try/except，且项目**未安装全局 sys.excepthook**——若异常发生，PySide6 打印 stderr 后继续（windowed 打包下完全静默）。但 `crop_snapshot` 的可预期异常已在 flow 层 `_abort` 兜住，剩余异常源≈MemoryError；且与基线 `load_from_clipboard`（150e005）完全同模式，「与粘贴同路」是 docstring 明示的有意沿用。更优解是装全局 excepthook（顺带覆盖粘贴等全部既有槽），而非只包这一个槽。

## 留档备注（归后续变更或下次审查）

1. **`load_from_clipboard` 仍无 busy 守卫**（main_window.py:177-186，预存问题、非本次引入）：d9d3139 只修了 `load_from_path`；粘贴入口仅靠 action 禁用兜底，而本次截图路径反而做了三层防护，同类入口防护强度不一。
2. **design D7 编号双义**：main_window.py:57 的「design D7」指 mvp-image-ocr 的 D7（原图/缩放副本分离），:213-214 的「design D7」指本变更的 D7（唯一自动识别输入），同文件无区分标注，建议后续写明变更名。
3. **全局 excepthook 缺失**（见 25-1）：事件循环内任意槽异常都不进 `ocrtool.log`，与「traceback 只入日志」的精神有缺口，值得后续变更统一装。
4. **决策关卡方法论**：1.6 的「无多屏硬件用 QT_SCALE_FACTOR+合成单测代偿」只覆盖了缩放系数维度，未覆盖屏原点偏移维度——后续涉及多屏的变更（如 background-residency 托盘、result-box-overlay 结果框叠加）应把「非原点屏全链路」列入关卡标准用例。

## 提交建议

1. **先修 100-1（必须）**：按修复方向 1 或 2 对齐坐标语义，并补非原点屏「框选→裁剪→内容颜色」端到端回归测试（用例骨架可参考评分代理的合成双屏注入法）。
2. **顺手同批修**：75-1（closeEvent→cancelled，约 5 行）、50-2（append/show 换序 2 行）、50-7（随 100-1 处置）、50-1（deleteLater 1 行）、50-3（补 1 个 keyClick 用例）、50-5（fixture 换 DottedDict）——均为低成本高确定性的修复。
3. 修复完成后随变更本体一并 `ADD:` 提交（含本 review.md），排除 `.idea/`；50-6 留到归档环节用 RENAMED 处理；25-1 与留档 1/2/3 归后续变更。
4. 工作区另有的三个纯提案目录（background-residency、model-switching、result-box-overlay）与本实现无耦合，建议与实现分开提交（另起 `ADD:` 规划件提交），保持变更历史可读。

---

## 修复落地记录（2026-08-22）

本体以 `954c848`（ADD: 屏幕区域截图识别与自动复制）入库后，按下节方案以红-绿流程修复。6 个新回归用例在未修复代码上全部失败、失败方式与本报告预测逐字吻合（副屏左半 → 静默取消；副屏右半 → finished 但内容为左偏 640px 的红色；外部关闭 → cancelled 不发射 + active=True + 主窗口不可见；隐藏期异常 → 主窗口不恢复），修复后全量 **246 passed**、`openspec validate --strict` 通过。

| 项 | 修复方式 | 验证 |
|---|---|---|
| 100-1 | 选**方向 1**：`RegionOverlay` 在过小判定与 `selectionDone` 发射前把选区 `translated(屏原点)` 转为全局逻辑坐标（尺寸提示同步）；坐标契约统一为「overlay 内部局部、跨模块全局」 | 新增 3 用例：副屏左半（红色 301×201）、副屏右半（蓝色 300×201，释放点 799 夹取含端点）、非原点屏 emit 全局坐标断言；红→绿 |
| 50-7 | 随方向 1 复活：`_show_overlays` 保存 `_snapshots`，信号接线改为 `_on_selection_done(rect)`（不再 lambda 绑定快照），内部用 `snapshot_at` 按全局 rect 中心定位所在屏；定位失败走 `_abort("截图选区异常")` | `snapshot_at` 恢复生产引用；既有直接调用用例适配新签名 |
| 75-1 | `RegionOverlay.closeEvent` → `cancelled.emit()`（`_ended` 守卫防递归，注释说明外部关闭语义） | 2 用例：裸 overlay close 发信号；flow 进行中 close → 收尾 + 覆盖层销毁 + 主窗口恢复 + active=False；红→绿 |
| 50-4 | `_hide_and_wait` 拆两步：`_window_was_visible` 在 `window.hide()` 副作用**之前**落账，返回值改 None | 新用例：monkeypatch `processEvents` 抛异常 → `failed` 发射且主窗口恢复；红→绿 |
| 50-2 | `_show_overlays` 中 `append` 移到 `show()` 之前 | 结构保证，注释留档 |
| 50-1 | `_cleanup` 尾部 `self.deleteLater()`（流程对象一次性，结束后自毁） | 既有用例兼容（deleteLater 推迟到事件循环，断言不受影响） |
| 50-3 | 补 `Ctrl+Shift+S` 按键级用例：FlowStub 替换 `RegionCaptureFlow` 计数创建，`QTest.keyClick` 断言恰好 1 次（0=ambiguous 双注册、>1=重复注册） | 现状即绿（防护缺口闭合，非缺陷修复） |
| 50-5 | `test_capture_entry` 的 window fixture 换 `DottedDict`，「默认开启」用例恢复对 key 写错的敏感性 | 现状即绿 |
| 50-6 | 不动 delta spec（标题匹配机制要求），**归档环节**用 RENAMED 处理 image-input 主规范标题 | 归档时执行 |
| 25-1 | 留档（全局 excepthook 缺失是根因，归后续变更；与基线 `load_from_clipboard` 同模式） | — |

修复提交：`FIX:` 一笔随本记录入库（产品代码 `region_overlay.py` + 测试 3 文件）。
