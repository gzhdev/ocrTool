# setup-project-baseline 代码审查报告

- **审查日期**：2026-08-22
- **审查对象**：dev 分支提交区间 `352972a..cc7c5b0`（本变更的全部实现提交，5 个，36 文件，+2868/−145；HEAD 即当前工作区，复审时 HEAD 未变）
- **对照规划件**：`openspec/changes/setup-project-baseline/`（proposal.md / design.md / tasks.md / specs/ 下 app-config、app-logging、app-paths、model-assets、packaging 五个 spec）
- **指南文件**：仓库根 `AGENTS.md`（本仓库无 CLAUDE.md，AGENTS.md 为等价物）
- **方法**：5 个并行审查代理独立审查（①AGENTS.md 红线合规 ②变更内浅层 bug 扫描 ③git 历史/演进一致性 ④spec 符合性 ⑤代码注释指引合规），每个候选问题再由独立评分代理按 0–100 置信度 rubric 复核，≥80 才计入必须报告项
- **环境说明**：仓库无远程、无 PR，报告直接输出于会话并留存本文件。工作区字面上的未提交变更仅 `.idea/ocr-tool.iml` 一行（IDE 自动添加 `src` 源码目录，无问题，不在审查范围）

## 一、审查结论

**无 ≥80 置信度的必须报告问题。** 候选问题共 3 个，评分 75×1、50×2，全部低于门槛，留档如下。

## 二、变更整体评价

实现质量高，与规划件高度一致，历史演进干净：

- **AGENTS.md 红线 11 项逐条通过**：`pyside6-essentials`（非元包）、opencv 断源 override + headless 直依赖（`tests/unit/test_dependency_constraints.py` 守护）、uv.lock 入库且 `uv sync --frozen`、模型权重不入库但 `model.json` 保留（`git check-ignore` 实证）、RapidOCR 显式本地路径 + `Global.use_cls: False`（死代理断网识别实测通过）、分层边界（本阶段无 UI，`--self-test` 直调属 tasks 1.3/1.8/7.6 规划的验收路径）、文件访问全经 `app/paths.py`、日志隐私边界（DEBUG 级实测无识别文本落盘）、PowerShell 脚本 + UTF-8 BOM（4 个 ps1 实测 `EF BB BF`）、`requires-python >=3.13,<3.14` 上界保留、spec 含 `collect_data_files/collect_submodules("rapidocr")`、提交信息中文带前缀。
- **spec 符合性**：5 个 spec 的全部 Requirement/Scenario 均有对应实现与测试，关键数字/名称/顺序契约一致（5MB×3 轮转、三层合并与 `.json.corrupt-<时间戳>` 备份、USER_ROOT 探测顺序与 `OCRTOOL_DATA_DIR` 无效即报错不回退、模型 `model.json` 必填字段含 `language_coverage`、id 重复集合级作废、配置 id → recommended → 排序首个 → None 回退链、models/config 与 exe 平级不进 `_runtime`、版本三处一致性）。
- **git 历史一致性**：全区间无删除/重命名/回退；后提交均为累积演进。tasks.md 42/42 勾选与实际交付吻合——`models.lock.json` 的 SHA256 与 `certutil -hashfile` 实测逐字符一致、release.ps1 死代理冒烟与 `--self-test` 输出契约吻合、`.gitignore` 例外实证生效、`openspec validate --strict setup-project-baseline` 实跑通过、设计书全文档无 `3.11`/`use_orientation` 残留。
- **注释指引合规**：paths.py「刻意不用 os.access」「未初始化抛错」、model_manager「文件名禁路径分隔符」「引擎参数唯一出口」、logger 隐私边界、spec excludes「第二道防线」、.gitignore 三条注释等逐项与实现一致。
- **浅层 bug 扫描排查通过的重点项**：rapidocr 参数键名与上游 config.yaml 逐项一致；ps1 脚本的 `$LASTEXITCODE` 检查、`finally` 清理、压缩 3 次重试正确；探针无残留文件；`Path(name).name != name` 可拦截 `../`、反斜杠与绝对路径穿越。

**结论：变更可以合并。**

## 三、75 分问题（1 个，建议合并前顺手修复）

### 3.1 非 CJK 代码页机器上发布冒烟必然崩溃（UnicodeEncodeError）

- **位置**：`src/ocrtool/main.py:100-102`（`for text in txts: print(f"  {text}")` 逐行打印中文识别文本；样本图 main.py:68 含「中英文混合识别冒烟验收」）；触发方 `scripts/release.ps1:33-36`（`Start-Process -RedirectStandardOutput/-RedirectStandardError` 重定向）与 `:46-48`（非零退出码即 `throw`，不产出 ZIP）。
- **机制**：Python 3.13 非控制台 stdout 使用本地 ANSI 代码页且错误处理器为 strict（PEP 686 的 UTF-8 默认要到 3.15，本项目锁 3.13）；打包产物 `console=True`（ocrtool.spec:73）且脚本未设 `PYTHONUTF8`，exe 行为与源码一致。
- **实证**：评分代理在本机（ACP=936）以 `PYTHONIOENCODING=cp1252` 模拟 en-US 重定向环境复现：`UnicodeEncodeError: 'charmap' codec can't encode`，exit=1，且 `SELF-TEST OK` 已先写出——与 release 关卡崩溃路径完全一致。
- **未达 80 的原因**：当前文档化工作流为 zh-CN 开发机（cp936 可编码中文）本地跑 release.ps1，恒不触发；仅换英文/西文 Windows 或 en-US CI 跑发布时必然命中。机制确凿但命中频率取决于发布环境。
- **修复方向（一行）**：`run_self_test()` 入口 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`（stderr 同理）；或按设计书「打印行数」原意删去逐行文本输出。不建议只在 release.ps1 设 `PYTHONUTF8`（会给 PS 读取侧引入新乱码变量）。

## 四、50 分低优先级问题（2 个，纯文档）

### 4.1 设计书 §8 存储模式摘要漏第三态 `OVERRIDE`

- **位置**：`OCRTool_桌面OCR开发设计书.md:473`（「存储模式：程序目录可写为 Portable（USER_ROOT = APP_ROOT），否则 Installed。」，经 `git show 613e5e4` 确认为本次新增 `+` 行）vs `src/ocrtool/app/paths.py:26-29,93`（三态枚举 PORTABLE/INSTALLED/OVERRIDE）与 `src/ocrtool/utils/logger.py:67`（启动日志实际会输出「存储模式=Override」）。
- **影响有限**：§8 正文（约 466 行）已完整记载环境变量覆盖及无效即终止行为；openspec spec 本身也只命名两态；AGENTS.md 无条款要求回写与枚举逐字一致。缺的只是摘要句中的第三态名称，读者看到日志 Override 时需查代码。
- **修复方向**：摘要句补「设置 `OCRTOOL_DATA_DIR` 时为 Override」。

### 4.2 设计书 §9.1 残留悬空字段 `confidence_threshold`

- **位置**：`OCRTool_桌面OCR开发设计书.md:506`（`"ocr": {"model": "ppocrv6-small", "confidence_threshold": 0.5}`）与 `:526`（「当前基线仅含 ocr/runtime/logging」的对齐声明）vs `config/default.json:2-4`、`src/ocrtool/config/defaults.py:11-13`（ocr 段仅 `model` 一个字段）。
- **git 裁决**：`613e5e4` hunk `@@ -508,9 +502,8 @@` 显示该示例块被整块重写（删 `use_orientation`、model 改 `ppocrv6-small`），`confidence_threshold` 行随重写重新输出（去尾逗号）——属**变更范围内的残留遗漏**，非预先存在问题。全仓库 grep `confidence_threshold` 仅设计书此一处，openspec 全部 specs（含 mvp-image-ocr）亦无该配置项规划。
- **影响有限**：纯文档示例，无运行时影响；AGENTS.md 权威顺序条款已把设计书列为第三优先「已部分作废」，spec 优先，误导实现的风险低；实现侧字段集另有测试锁定。
- **修复方向**：删除该字段行，示例 ocr 段只留 `model`。

## 五、留档备注（非问题，归后续变更）

1. **UI 接线延后**（mvp-image-ocr 范围）：app-logging「用户界面仅显示一条可读的中文说明」与 model-assets「向用户提示」的 UI 半边，本变更无 UI 属预期；config 侧已有 `ConfigManager.warnings`（manager.py:50,100-102）、model 侧已有 `ScanResult.errors`/`resolve_model()→None` 把信息暴露给调用方，但 `main.py:47` 目前丢弃自检返回值——mvp 落地状态栏时应接线。
2. **发布残留断言完备性**：packaging spec 冒烟场景的「退出后未在程序目录之外留下预期以外的文件」子句在 release.ps1 中无显式断言；当前 Portable 模式行为由 paths 设计保证，属验证完备性而非行为不符。

## 六、提交建议

本报告属变更的规划件补充，随版本控制提交。75 分问题 3.1 修复成本一行，建议与本报告一起落地（或变更本体先提交、修复另起 `FIX:` 提交）；两个 50 分文档项可顺手改，也可不动。
