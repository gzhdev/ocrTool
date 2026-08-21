# 工程基线与打包骨架技术设计

## Context

动机见 `proposal.md — Why`；行为契约见 `specs/`。此处只记录支撑这些契约的技术决策。

约束来自三方面：

1. **上游事实**（已实测确认，非推测）
   - `rapidocr 3.9.2` 的 `OCRVersion` 含 `PP-OCRv6`，`ModelType` 含 `TINY/SMALL/MEDIUM`；v6 的识别模型为 `multi_PP-OCRv6_rec_*`，是统一多语种模型而非按语种拆分。
   - `rapidocr` 默认从 ModelScope 拉取模型，其 `default_models.yaml` 中每个模型条目附带官方 SHA256。
   - `rapidocr` 硬依赖 `opencv-python`（非 headless），其传递依赖为 `pyclipper / numpy / shapely / omegaconf / PyYAML / Pillow / tqdm / requests / colorlog / six`。
   - Python 3.13 的 win_amd64 wheel 齐备：`onnxruntime 1.29.0 (cp313)`、`PySide6 6.11.2 (cp310-abi3)`、`pyclipper (cp313)`、`shapely (cp313)`、`opencv (cp37-abi3)`；`uv` 解析 32 包零冲突。
   - `onnxruntime 1.29.0` **无 cp314 wheel**。
   - `PyInstaller 6.22.2` 的 `requires-python` 为 `<3.16,>=3.8`，classifier 明确列出 3.13。

2. **设计书既有约定**：`OCRTool_桌面OCR开发设计书.md` §7 发布目录、§29 组件裁剪、§30 onedir、§42 无网络、§43 隐私。

3. **当前仓库状态**：`pyproject.toml` 为空壳（`requires-python = ">=3.13"`，无依赖），`.venv` 为 3.13.14，`src/` 尚不存在。

## Goals / Non-Goals

**Goals:**

- 让「解压双击能跑」这一验收标准在**业务代码存在之前**就被验证，把打包风险前移。
- 把设计书中「禁止 X」形式的约束，落成依赖声明与构建配置层面的**强制机制**，而非依赖开发者自觉。
- 让模型成为可独立替换的外部资产。

**Non-Goals:**

- 不实现任何 OCR 业务逻辑、UI 交互或图片输入——归 `mvp-image-ocr`。
- 不提供模型切换界面、多模型并行加载或模型下载器 UI。
- 不做自动更新、安装程序、代码签名。
- 不追求发布体积最优化（仅裁掉明确无用的组件，不做 DLL 级别精简）。

## Decisions

### D1：Python 基线取 3.13，且封闭上界

采用 `requires-python = ">=3.13,<3.14"`。

- **为何不是 3.11**（设计书 §57 原值）：3.11 无任何技术优势，且当前 `.venv` 与 `pyproject.toml` 已是 3.13，回退需要额外的环境重建成本。实测证明 3.13 全链路 wheel 齐备。
- **为何必须封上界**：`onnxruntime 1.29.0` 只发布到 cp313。若保持 `>=3.13` 开区间，任何装有 3.14 的机器执行 `uv sync` 会解析失败，且错误信息指向 onnxruntime 而非版本约束，排查成本高。上界是对**尚不存在的 wheel** 的防御。
- **权衡**：上界意味着 Python 升级需要一次显式的依赖复核。这是有意为之——推理运行时的 ABI 兼容性不应被静默跨越。

### D2：依赖 `pyside6-essentials`，不依赖 `pyside6` 元包

- `pyside6` 元包 = `pyside6-essentials`(73 MB) + `pyside6-addons`(160 MB)。addons 内含 QtWebEngine / QtMultimedia / Qt3D / QtCharts，正是设计书 §29 点名禁止的组件。
- **替代方案**：依赖 `pyside6` 再靠 PyInstaller `excludes` 剔除。**否决**——那是在产物侧做减法，开发环境仍会安装 160 MB，且 excludes 名单一旦遗漏就静默进包。从依赖侧断源是单点、可验证的。
- PyInstaller 的 `excludes` 仍然保留，作为**第二道防线**而非主要机制。

### D3：将 `opencv-python` 覆盖为 `opencv-python-headless`

- `opencv-python` 自带一套 Qt5 平台插件。与 PySide6 同进程时，两套 Qt 运行时会导致 `qt.qpa.plugin: Could not load the Qt platform plugin "windows"` 并闪退。这是 rapidocr + PySide6 组合特有的问题。
- 通过 `[tool.uv] override-dependencies` 覆盖 rapidocr 声明的 `opencv_python`。
- **代价评估**：两个 wheel 体积几乎相同（42.0 MB vs 41.8 MB），headless 仅去掉 GUI 相关模块，而本项目只使用 opencv 的图像数组处理能力。**覆盖无功能损失**。
- **风险**：override 是全局性的，若将来引入其他需要 opencv GUI 的依赖会冲突。当前无此需求，且若出现应优先质疑该依赖。

### D4：双根路径模型

设计书 §8 将 8 个路径挂在单一 `APP_ROOT` 下，这是可写性问题的根因。拆分为：

```
APP_ROOT   (只读, = exe 同级 / 开发时项目根)  ->  models/  config/  resources/
USER_ROOT  (可写, 探测得来)                   ->  data/    logs/    cache/
```

- **探测顺序**：`OCRTOOL_DATA_DIR` 环境变量 → `APP_ROOT` 实写探针 → `%LOCALAPPDATA%\OCRTool`。
- **为何用实写探针而非 `os.access(W_OK)`**：Windows 上 `os.access` 只反映只读属性，不解析 ACL，对 Program Files 会给出假阳性。必须真实 `open(..., 'w')` 一次再删除。
- **为何环境变量无效时硬失败**：自动探测的回退是系统在替用户决策，可以静默；而环境变量是用户的显式指令，静默忽略会造成「我明明指定了目录，数据却写到别处」的困惑。
- **副产物**：Installed 模式下 `data/` 天然位于程序目录之外，设计书 §45 中「升级时手工复制 config.json」的建议随之作废。

### D5：模型标识与目录名解耦

设计书 §10.1 用固定目录名 `default`，与 §46「多版本模型并存」自相矛盾。三个概念分离：

| 概念 | 载体 | 例 |
|---|---|---|
| 目录名 | 文件系统，任意 | `models/ppocrv6-small/` |
| 唯一键 | `model.json` 的 `id` | `ppocrv6-small` |
| 当前选择 | 配置项 `ocr.model` | `ppocrv6-small` |

- `default` 降级为**回退策略名**而非目录名。回退链：配置指定 → `recommended: true` → 扫描首个 → 自检失败。
- `model.json` 的 `languages` 字段语义需修正：PP-OCRv6 的识别模型是统一多语种模型，该字段描述「覆盖语种」而非「模型按语种拆分」。
- **本变更只实现「解析」，不实现「切换」**。扫描与校验是解析的必要组成，但运行期模型切换、模型列表 UI 归后续版本。理由：第一版只内置一个模型，切换逻辑无处验证。

### D6：模型不入版本库，改为带校验的获取脚本

- `.gitignore` 排除 `models/**/*.onnx`，但**保留** `models/**/model.json`——元数据是契约的一部分，应受版本控制。
- `packaging/models.lock.json` 登记 `id / 文件名 / URL / SHA256`，SHA256 直接取自 rapidocr 上游 `default_models.yaml`，不自行计算。
- 获取脚本幂等：已存在且哈希匹配则跳过；哈希不匹配则删除并失败。
- **替代方案对比**：

| 方案 | 否决理由 |
|---|---|
| Git LFS | 内网环境常无 LFS 支持；且模型本质是外部产物而非源码 |
| 直接提交二进制 | 仓库膨胀，且每次模型升级产生数十 MB 的不可 diff 提交 |
| 手工放置 + 文档说明 | clone 后无法直接运行，新人上手成本高，CI 无法自动化 |

- 内网部署时替换 lock 文件中的 URL 为镜像地址即可，无需改代码。

### D7：禁网靠「显式传路径」而非「拦截网络」

rapidocr 在未指定 `model_path` 时会联网下载。阻断方式是**始终显式传入本地路径**，使下载分支不可达；而非在进程级别拦截网络调用。

- **替代方案**：monkeypatch `requests` 或设置代理陷阱。**否决**——脆弱、难以推理，且会影响将来可能引入的正当网络功能。
- 配套：模型缺失时由自身的模型解析层报错，错误信息指向本地路径，不暴露上游的下载语义。

### D8：PyInstaller 以 spec 文件为单一来源

废弃设计书 §31 的命令行方案。`packaging/ocrtool.spec` 必须包含：

```
datas         = collect_data_files("rapidocr")     # config.yaml / default_models.yaml / 字典
hiddenimports = collect_submodules("rapidocr")     # 动态导入的子模块
excludes      = [WebEngine, Multimedia, Qml, Quick, 3D, Charts, tkinter, ...]
contents-directory = "_runtime"                    # 设计书 §7
```

- **`models/` 与 `config/` 绝不进 `datas`**。它们必须与 exe 平级（设计书 §7），由构建脚本在 PyInstaller 之后复制。若误入 `datas`，会落到 `_runtime/models/`，运行时 `APP_ROOT` 解析不到——这是一个会在打包后才暴露的静默失败，需在构建脚本中显式断言目录位置。
- 沿用 onedir（设计书 §30 已论证）。

### D9：日志隐私靠「主动接管第三方 logger」

rapidocr 持有独立的 `RapidOCR` logger，会向 stderr 输出识别内容，绕过本项目的日志配置。需在 OCR 组件初始化时清空其 handler 并断开传播。这是 `app-logging` 中「第三方组件输出被抑制」场景的实现依据。

## Risks / Trade-offs

- **打包产物在干净机器上不可运行** → 本变更唯一无法静态消除的风险。缓解：将冒烟验收作为发布流程的强制关卡，且在业务开发开始前先跑通一次最小骨架的打包（见 Migration Plan 第 1 步）。
- **`collect_data_files("rapidocr")` 收集范围过大** → 可能带入全部语种字典，增大体积。缓解：先求正确再求精简；体积超出预期时再按实际需要收窄，且收窄后必须重跑冒烟验收。
- **上游 rapidocr 再次破坏性变更** → 3.x 已相对稳定，但 2.x→3.x 的前车之鉴仍在。缓解：锁定 `uv.lock`；模型解析与引擎调用的边界收敛在少数模块内（具体抽象由 `mvp-image-ocr` 的 `ocr-engine` 承担）。
- **`opencv-python-headless` 覆盖引入未知副作用** → rapidocr 若在某路径使用 opencv GUI 函数会运行时报错。缓解：冒烟验收覆盖真实识别路径即可暴露。
- **上界 `<3.14` 造成依赖僵化** → Python 升级需人工复核。这是有意接受的成本，见 D1。
- **Installed 模式下用户找不到日志** → 用户以为日志在程序目录。缓解：启动日志与界面「关于」信息中显示实际的 `USER_ROOT` 路径。

## Migration Plan

项目为全新工程，无存量数据需迁移。落地顺序按「风险从高到低」而非「模块从底到顶」：

1. **打包 spike 优先**：以一个仅创建空窗口 + 加载模型执行一次识别的最小骨架，先跑通 `pyproject → uv sync → PyInstaller → 干净机器运行`。此步失败则技术选型需重新评估，后续全部工作暂停。
2. 依赖基线固化（D1/D2/D3）+ `uv.lock` 提交。
3. 路径与存储模式（D4），先于日志。
4. 日志与配置。
5. 模型资产契约、获取脚本与解析（D5/D6/D7）。
6. 构建与发布脚本，冒烟验收自动化（D8）。
7. 回写 `OCRTool_桌面OCR开发设计书.md` 中已失效的 §8 / §10 / §26 / §29 / §31 / §45 / §57。

回滚策略：各步骤均为新增文件，无存量行为被替换；任一步骤失败可直接丢弃该步产物而不影响前序步骤。

## Open Questions

- **PP-OCRv6 识别模型是否自带字符字典？** 上游 `default_models.yaml` 中识别模型条目只列单个 `.onnx` 文件，推断字典嵌于 ONNX metadata。若实际需要独立的字典文件，`models/<dir>/` 的目录契约需增加一项。此问题在 Migration Plan 第 1 步的 spike 中即可确认，且只影响模型目录的文件清单，不影响解析规则与回退顺序。
- **发布产物的实际体积**（初步估计 220~280 MB）与冷启动耗时是否满足设计书 §27 的参考目标。两者均为参考指标而非验收门槛，测得后据实记录，不预设结论。
