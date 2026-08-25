# background-residency 代码审查报告

## 审查元信息与结论

- **审查对象**：提交 `719105e`（HEAD，「ADD: 后台常驻与系统集成（background-residency）」，25 文件 +2416/−56）
- **变更范围**：新增 `src/ocrtool/platform/{single_instance,hotkey,autostart}.py`（774 行）、`src/ocrtool/ui/tray.py`、`src/ocrtool/ui/widgets/hotkey_capture_dialog.py`、`resources/icons/tray-*.png` 五张、`scripts/gen_tray_icon.py`；修改 `application.py`（+151，单实例/自愈/托盘/热键装配与 `_release_resources`）、`main_window.py`（+115，closeEvent 两分支/bring_to_front/热键绑定）、`config` 新增 5 键、`build.ps1` 增 Copy-Item resources；测试五处（含真实子进程集成 `_residency_probe.py`）；设计书 §36/§36.1/§43/§43.1 回写、tasks.md 43/47 勾选（4.3/4.7 真实注销重登与 5.2 八小时长跑需用户手动验收）
- **方法**：变更摘要代理 + 5 并行审查代理（AGENTS.md 合规 / 浅层 bug / git 历史回归 / 既往审查适用性 / 注释指引）→ 汇总去重 15 个候选 → 10 个并行评分代理独立验证（rubric 0/25/50/75/100，≥80 必须报告）→ 过滤
- **验证证据**：评分代理对重点项做 offscreen/ctypes 探针实测（Shift+数字组合链、模态对话框期间原生事件过滤器、私有池 vs 全局池 waitForDone 计时、QDialog 累积计数、普通 dict 点路径 miss）；既往 10 笔 FIX 提交逐一核对无回退；提交信息自述全量 406 passed（审查未重跑全量）
- **结论**：**无 ≥80 置信度必须报告问题**。3 项 75 分（建议 FIX 提交修复，评分代理均独立实证）+ 1 项 60 分 + 10 项 50 分 + 1 项 40 分留档。变更主体机制质量高，可继续推进。

## 变更整体评价

- **单实例（D2/D3/D4）机制正确**：QLocalServer 端点按 `sha256(user|app_root.casefold())` 派生（目录隔离）→ 连接探测 → 命名互斥量原子仲裁（真实 exe 双启动竞态实测发现后补）→ 陈旧端点清理 → listen；任何失败降级 DEGRADED 不阻塞启动。集成测试以真实子进程覆盖 taskkill /F 五连重启、双目录并存、端点复用。
- **热键（D5/D6）注册式实现干净**：ctypes RegisterHotKey（无键盘钩子，privacy 友好）、WM_HOTKEY 经原生事件过滤器、长按抑制用键态轮询+等待释放状态机（30ms GetAsyncKeyState，纯时间阈值被注释明确否定并有真实桌面实测：6 连自动重复恰触发一次）、四层黑名单、rebind 失败恢复旧组合。
- **自启（D8）与托盘（D7）**：heal 等价不重写（大小写/斜杠风格不误判）；托盘不可用降级前台程序、程序化刷新勾选 blockSignals 防回灌（QSignalBlocker 原则语义遵守）；解除 quitOnLastWindowClosed 同批补齐退出入口（托盘退出 + 关闭不驻留 quitRequested）。
- **AGENTS.md 红线逐条通过**：QtNetwork 实测属 pyside6-essentials；新增约 25 处日志逐条过目只含端点哈希/错误码/异常/注册表值名（热键日志的 `combo.format()` 是自身配置数据且 spec 明文要求记录失败原因）；托盘/热键均以信号接入既有分层（UI 未触引擎）；文件访问经 `paths.resource_dir()`/`get_app_root()`；启动路径无 ONNX 加载。
- **既往审查教训未重犯**：无信号双注册、busy/token 守卫未绕过（热键经 start_region_capture 双守卫）、config 两层默认一致（既有 test_config 全量锁定测试自动覆盖 5 新键）、tray 程序化静默有专项测试、10 笔 FIX 修复点全部保持。
- tasks.md 43/47 与交付吻合（唯 5.7 行重复致账目口径错乱，见 50-7）。

## 75 分问题（建议 FIX 提交修复，均附修复方案）

### 75-1 绑定 Ctrl+Shift+数字组合使全局热键静默彻底失效（含未捕获 KeyError）

- **位置**：`src/ocrtool/ui/widgets/hotkey_capture_dialog.py:50`（根因：`QKeySequence(key).toString()` 从 `event.key()` 取主键名）；`src/ocrtool/platform/hotkey.py:144-145`（`native_vk()` 裸查 `_KEY_VK` 表，KeyError 放大器）
- **机制**：Shift 按下期间 `event.key()` 返回布局映射后的符号键（Windows 平台 Qt keymapper 经 ToUnicode 按修饰槽位预计算，美式布局 Shift+1 → Key_Exclam → 字符串 `!`）。对话框 `except ValueError` 是死代码（HotkeyCombo 无校验），非法组合被**接受**；随后 `apply_hotkey_combo → rebind → register` 先注销旧热键，`native_vk()` 对 `!` 抛**未捕获 KeyError**——旧热键已丢、新热键未注册、配置未写、状态区无提示，全局热键静默彻底失效。
- **实证**：offscreen 注入 QKeyEvent——Ctrl+Shift+1..0 十个组合全部产出 `!@#$%^&*()` 且全部被接受为 `Ctrl+Shift+!` 等；KeyError 在 rebind 链实测复现；俄语布局字母（U+0424）产出 `Ctrl+Alt+Ф` 同理；对照组 Ctrl+Alt+Key_1 正常。中文 Windows 默认拼音 IME 叠加美式布局，Shift+数字行为与美式一致，Ctrl+Shift+数字是常见热键形态。
- **spec 违反**：global-hotkey delta「重新绑定失败 MUST 保持原组合注册并界面提示」（两条 MUST 同时违反）+ design D6「不产生设置了却无效的错觉」。
- **修复方案**：①对话框解析对可打印字符键先映射回 unshifted 基础键（如按 `event.text()` 反查或维护 shift 映射表），非拉丁布局字母可用 `event.nativeScanCode()`/`nativeVirtualKey()` 回退；②`native_vk` 对未知主键抛可读错误（HotkeyError），`rebind` 的失败恢复路径兜住——即使①遗漏也不至于静默失效；③补「Ctrl+Shift+数字可绑定且注册成功」回归用例。

### 75-2 托盘菜单「截图识别」未置前窗口，驻留态结果静默进剪贴板

- **位置**：`src/ocrtool/app/application.py:162`（`tray.captureRequested.connect(window.start_region_capture)` 直连无置前）；对照 `src/ocrtool/ui/main_window.py:492-499`（热键路径先 `bring_to_front()`，注释明言「不把结果静默丢进剪贴板」）；恢复语义在 `src/ocrtool/capture/region_overlay.py:226`（`_window_was_visible` 落账）与 `:306-309`（仅 was_visible 才恢复）
- **机制**：RegionCaptureFlow 结束只恢复「发起前可见」的窗口；托盘入口发起时窗口处于隐藏驻留态（这正是从托盘发起的前提），选区完成后窗口不恢复，结果只进不可见窗口的状态区 + 剪贴板（auto_copy 默认开）；用户关掉 auto_copy 后结果无任何可见反馈——「点菜单、框选区、无事发生」。同一提交内热键与托盘两条等价入口行为分裂（git -L 确认均为 719105e 新增）；tasks.md:103 作者自立契约「结果不静默丢弃」仅热键路径兑现。
- **实证**：评分代理逐环核实行为链（接线、落账、恢复、结果去向）；proposal.md:38 将「截图识别」明文列为托盘菜单能力——主路径而非边角。
- **修复方案**：托盘连接改为经与热键共用的小方法（先 `bring_to_front` 再 `start_region_capture`）；补「驻留态从托盘发起截图，完成后窗口恢复可见」回归。

### 75-3 退出排空机制等待了错误的线程池

- **位置**：`src/ocrtool/app/application.py:181`（`QThreadPool.globalInstance().waitForDone(_SHUTDOWN_DRAIN_MS)`）；正确锚点 `src/ocrtool/controllers/ocr_controller.py:79-82`（`pool` property，docstring 明言「暴露线程池供显式等待」却未被使用）
- **机制**：OCR 识别与模型切换 worker 全部提交在 controller 自建容量 1 **私有池**（`ocr_controller.py:50`）；`git grep globalInstance` 全 src/ 唯一命中就是 application.py:181 本身——全局池上从未有任务，10 秒排空窗口确定性无效。三处注释/测试断言了不存在的行为：`main_window.py:447`（「退出流程会等待其完成」）、`application.py:35-36`（`_SHUTDOWN_DRAIN_MS` 注释）、`tests/unit/test_tray_ui.py:219`。
- **实证**：纯 QtCore 实验——私有池跑 1.5s 任务时 `globalInstance().waitForDone(10_000)` 0.000s 立即返回（等空池），`pool.waitForDone(10_000)` 阻塞 1.503s。与 system-tray delta「识别进行中退出：MUST NOT 出现无响应或崩溃」场景关联（注释直接引用该 spec）。
- **影响权衡**（75 非 100 的原因）：私有池析构仍会无超时 waitForDone 兜底（上轮归档 review 实测慢 worker 退出不崩），用户可观察影响极小；但兜底与注释声称的「超时强制退出」恰好相反——onnxruntime 线程真卡死时进程永久挂住，正是注释声称要防的场景。
- **修复方案**：一行改 `controller.pool.waitForDone(_SHUTDOWN_DRAIN_MS)`；三处误导注释随之核实修正；补「识别在途退出，排空窗口真实等待」回归（可用假 worker 提交私有池后断言 waitForDone 耗时）。

## 60 分问题

### 60-1 设计书 §9.1 配置示例第四次漏更（历次漏面最大）

- `OCRTool_桌面OCR开发设计书.md:518-550`：本次新增 5 键（ui.close_to_tray/ui.start_minimized/ui.tray_hint_done/hotkey.capture/system.auto_start）全书 grep 零出现，也无 hotkey/system 两个新顶层段——§36/§36.1/§43/§43.1 回写齐整唯独 §9.1 又漏。既往三连（setup 4.2 残留 confidence_threshold / mvp 50-7 缺 max_edge_px / result-box 50-3 缺 show_boxes，均 50 分档已修），本次为同模式第四次且首次 100% 漏更（5 键全缺），评分代理据此从既往 50 档上调至 60。纯文档零运行时影响（实现侧 test_config.py 全量锁定）。修复：§9.1 示例补 5 键 2 段。

## 50 分问题（留档，可顺手修）

1. **对话框打开期间按当前热键叠出截图覆盖层**：`main_window.py:490`——`nativeEventFilter` 不受模态对话框阻止（双探针实证：模态 exec 期间 WM_HOTKEY 全链同步执行），热键路径触发截图覆盖层叠在对话框上（对话框还会被拍进冻结帧）。评分代理修正原陈述：RegisterHotKey 在系统层吞掉组合的普通键盘投递，对话框 keyPressEvent 收不到主键，「双流程交叉 rebind」不成立——单向且可自愈（覆盖层可 Esc）。修复：对话框打开期间挂起热键（unregister/rebind 或标志位）。spec 无「设置期间挂起」场景，属空白。
2. **多目录副本共享固定 Run 值名互抢**：`autostart.py:28` `VALUE_NAME="OCRTool"` + `application.py:141` 无条件 heal——触发面比初判宽：只要 A 开自启、B（从未开启）运行过一次，B 的 heal 就抢写启动项且 B 托盘凭空显示「已开启」；B 上关闭还会删掉 A 的项。与单实例按目录派生的隔离不对称（同提交内机制分裂）。但 spec/design 未覆盖「自启×多副本」（D4 已知后果清单只豁免了全局快捷键冲突），低频场景。修复方向：值名仿 `endpoint_name` 按目录哈希派生。
3. **识别中按热键先弹窗后静默拒绝**：`main_window.py:492-499` `bring_to_front()`（含抢焦点）在 busy 守卫之前——违反 d9d3139 确立的「拒绝时无副作用」形态（托盘路径 busy 时零副作用，反衬热键路径是顺序疏忽）。触发面真实（连续识别多处屏幕的工作流）。修复：置前移到 busy 检查后，或 busy 时提示。
4. **assert_dist 未断言 resources/**：`build.ps1:43` 新增外置资产无 `assert_dist.ps1:13-27` 对应断言（models/config 均有）；图标缺失只 ERROR 日志空图标继续、`--self-test` 不触图标、release.ps1 不独立调用 assert_dist——防线只有 build 内部一次。当前零故障（Copy-Item 无条件执行且图标已入库），防御性缺口。修复：补 resources 存在性断言（一行）。
5. **互斥量竞态分支不激活已有实例 + 注释以偏概全**：`single_instance.py:159-167` ERROR_ALREADY_EXISTS 分支静默退出不发激活消息（该分支可达前提是对方未监听，无管道可写，属端点方案固有局限）；持续缺口仅 DEGRADED-but-holding-mutex（listen 失败极罕见）下双击永久无反应。`application.py:127-129` 概括注释把静默分支覆盖进「传达激活意图」（库内注释自洽）。修复：注释补例外说明；DEGRADED 场景可在持互斥量但 listen 失败时释放互斥量放弃单实例（与「以放弃单实例为代价继续可用」语义对齐）——酌情。
6. **快捷键对话框每次打开累积 QDialog 不释放**：`main_window.py:501-510` exec 后无 deleteLater/WA_DeleteOnClose——探针实证 20 次后 findChildren(QDialog)==20。既往 50-1 同构第三案（5018453/b7fecbe 修复模式：exec 后 `deleteLater()`）。每次约 5 个 QObject + 原生窗口句柄，低频操作。
7. **tasks.md 5.7 重复行致账目错乱 + 2.7 注记归因错误**：tasks.md:114 新增勾选行而 :116 提案原行未删——真实完成度 **44/47**（提交信息「43/47」为分子虚低 1，评分代理修正原「43/46」口径）；tasks.md:48 注记「热键注销在析构/aboutToQuit 自动覆盖」与实现（`_release_resources` 显式调 `hotkey.shutdown()`）不符。修复：删重复行、改注记（model-switching 50-2 同类先例）。
8. **新测试真实触碰系统资源**：`test_hotkey.py` 真实 RegisterHotKey（冷门组合+finally 清理）、`test_autostart.py` 真实写 HKCU Run（UUID 值名+fixture 清理）、`test_tray_ui.py` 真实创建托盘图标（tray.shutdown 收尾）——既往「写真实剪贴板」留档级模式的加强版，docstring 明示有意决策且有缓解；唯一强杀后持久残留的是 `OCRTool-Test-<uuid>` 无效注册表值（值名隔离）。沿既往留档处理，后续可统一加 skip 标记。
9. **application.py:7-9 模块 docstring 启动顺序与实际相反**：docstring「单实例检测 → 解除 quitOnLastWindowClosed」，实际先解除（:125）后检测（:130）。无行为差异（检测命中时进程即退）。
10. **hotkey.py:9 docstring「时间阈值抑制」与实现矛盾**：实为键态轮询+等待释放状态机，同文件 :29-33 常量注释明确否定时间阈值方案——文件内两注释自相矛盾（model-switching 50-2 同类）。

## 40 分问题（降档说明）

1. **TestShowDecision 两用例传普通 dict 点路径恒 miss**（`tests/unit/test_tray_ui.py:247-256`）：恒 miss 代码事实成立，但评分代理降档——「防御深度 2→1」不成立：dict 恒 miss 使该两用例成为全文件唯一对「回退默认值写错」敏感的用例（miss 才暴露回退值），照既往模式换 DottedDict 反而失去这层意外防护；且 `--tray` 用例中 config.get 因短路根本不执行。**不建议照搬既往修复模式**，维持现状或加注释说明 fixture 选择理由。

## 留档备注（不计问题）

1. 75-1 的评分过程实证了「对话框 except ValueError 是死代码」（HotkeyCombo 无校验 dataclass）——「不支持的主键」文案只在 parse() 路径存在，对话框路径无任何校验反馈，属 75-1 修复方案①的附带覆盖面。
2. 单实例激活消息靠 250ms QEventLoop 固定延时送达（waitForBytesWritten 实测无效）——命名管道本地回环下足够，注释已如实说明，机制可用。
3. `_residency_probe.py` 子进程夹具写标记文件于 tmp_path（测试基建，不触「不产生临时文件」红线——该红线约束应用运行期）。
4. 4.3/4.7（真实注销重登）与 5.2（8 小时长跑）三项待用户手动验收——机制侧单测与真实 exe 证据齐备，验收后勾选。

## 提交建议

- 变更已提交（719105e），主体机制（单实例/热键/自启/托盘）质量高、AGENTS.md 全量通过，可继续推进。
- 三个 75 分项建议另起一笔 `FIX:` 提交（75-1 约 20 行+用例、75-2 约 5 行、75-3 一行+注释核实，合计一个下午工作量），修复后在本文件追加修复落地记录；60-1（§9.1 补 5 键 2 段）与 50 分中的 4/6/7（一行级）建议随批顺手处理。
- 三个 75 分项共同点：**新增交互路径的收尾**（重绑崩溃链、托盘截图反馈、退出等待）——与主体机制无关，均为装配/边界层缺陷。

## 修复落地记录（2026-08-25）

红绿流程：每项先写红测试在未修复代码上复现，再修复转绿。全量 **425 passed**（修复前 406，新增 19 个回归用例）。

| 项 | 修复方式 | 验证（红 → 绿） |
|---|---|---|
| 75-1 符号键链 | ①对话框 `_key_name_for`：十个数字符号键（Key_Exclam→'1' 等）映射回 unshifted 主键；构造改经 `HotkeyCombo.parse` 统一校验（对话框不再绕过）②`register` 在注销旧组合**之前**加 `_KEY_VK` 存在性前置校验，未知主键走 last_error 可读路径；`native_vk` 兜底抛 `HotkeyError` | 红：Ctrl+Shift+Key_Exclam 被接受为 `Ctrl+Shift+!` + rebind 链 `KeyError('!')` 且 `registered=False`；绿：13 用例（十符号映射 / Key_Less 可读拒绝 / register 未知主键 False 不抛 / rebind 恢复原组合且 message 含「不支持」） |
| 75-2 托盘截图不置前 | 新增 `MainWindow.start_capture_and_show()` 共用入口（置前 + 截图），托盘 `captureRequested` 与热键 `_on_global_hotkey` 均接此 | 红：方法不存在（3 用例）；绿：驻留态共用入口先置后截图、全局热键与托盘同入口 |
| 75-3 排空等错池 | `_release_resources` 改 `controller.pool.waitForDone(_SHUTDOWN_DRAIN_MS)`；三处注释核实（closeEvent docstring、`_SHUTDOWN_DRAIN_MS`、test_tray_ui 注释） | 探针已证全局池 0.000s 立返 vs 私有池 1.102s；回归锚点 `TestShutdownDrainPool`（私有池真实等待 >0.3s + 全局池空对照） |
| 60-1 §9.1 漏更 | 示例补 5 键 2 段（ui 三键 + hotkey.capture + system.auto_start）+ 注意段说明默认值语义与注册表真源 | grep 五键全书出现；与 defaults.py/config/default.json 三处一致 |
| 50-1 对话框期间热键未挂起 | `_open_hotkey_dialog` 进入时 `unregister`（挂起前保存组合），结束路径统一恢复（rebind 成功则新组合已注册；取消/失败则重注册原组合） | `test_对话框期间挂起热键_取消后恢复`：模态期间 registered=False，结束后恢复（calls 序列 register→unregister→register） |
| 50-3 busy 时先置前 | busy 守卫移到 `start_capture_and_show` 首行（拒绝时零副作用：不置前不截图，仅状态区提示） | `test_识别中共用入口拒绝且无置前副作用`：busy 下窗口保持隐藏、截图零调用 |
| 50-4 assert_dist 缺 resources | 补 `resources/icons/tray-256.png` 存在性断言 | `assert_dist.ps1 -DistDir dist/OCRTool` 通过（产物含图标） |
| 50-5 互斥量静默分支 | listen 失败（DEGRADED）时释放互斥量（`_release_mutex`），与「以放弃单实例为代价继续可用」语义对齐；application 概括注释补竞态分支例外说明 | 既有降级用例回归通过（DEGRADED 不再持仲裁） |
| 50-6 对话框累积 | exec 后 `finally: dialog.deleteLater()` | `test_对话框exec后释放不累积`：20 次开合 + DeferredDelete 派发后 findChildren 为空 |
| 50-7 tasks.md 账目 | 删 5.7 重复未勾行（真实完成度回到 44/47）；2.7 注记改为「显式调用 hotkey/guard/tray.shutdown + 控制器私有池有界排空」 | grep 5.7 单行；注记与 `_release_resources` 实现一致 |
| 50-9 docstring 顺序 | application 模块 docstring 改「解除 → 单实例检测 → …」与实际执行序一致 | 人工核对 |
| 50-10 docstring 矛盾 | hotkey 模块 docstring「时间阈值抑制」改「等待释放状态机 + 30ms 键态轮询」 | 与 `_RELEASE_POLL_MS` 常量注释一致 |
| 50-2 多副本值名互抢 | **未修**（spec/design 未覆盖自启×多副本，涉及旧值迁移逻辑，留待单独变更） | — |
| 50-8 测试触真实资源 | **留档**（沿既往处理，值名 UUID 隔离 + finally 清理已缓解） | — |
| 40-1 TestShowDecision dict 恒 miss | **不修**（报告自身不建议：恒 miss 意外提供回退默认值敏感性） | — |
