# 谱间 · Video TAB to GP5

将视频中的动态 TAB 或已有 PDF 转成可编辑的 Guitar Pro 5（`.gp5`）草稿。本机运行，当前重点支持 **四弦 / 五弦贝斯、纯 TAB / 五线谱＋TAB**，不做音频听写。

**当前发布版本：`v0.3.0`。** [下载发布包](https://github.com/Bionysus-bot/video-tab-to-gp5/releases/tag/v0.3.0) · [版本记录](CHANGELOG.md) · [五弦说明](docs/FIVE_STRING_BASS.md)

本版已合并至 `main`，并作为 GitHub Latest 发布。此前预发布版和旧版本保留，可按标签回退。识谱结果需对照原图核对；可先下载带疑点标注的草稿，再逐步修正。通过程序检查不等于所有音符准确。

## 本版更新

- **简洁工作区**：准备素材、自动识谱、结果校对分成三个视图；暖白浅蓝配色、中文像素字体和紧凑首屏。
- **四弦 / 五弦贝斯**：四弦默认不变，五弦增加最低 B 弦、第五弦编辑和 GP5 输出。
- **调弦方案直接选择**：显示音名，不要求填写 MIDI 数值。
- **自动草稿与版本保留**：识谱结果独立保存，保留已知音符、缺失提示及旧版本；可下载有疑点的草稿。
- **单小节 / 批量确认**：保存修改、生成新草稿，并去掉已确认小节的谱内核对文字。结构错误或音符缺失的小节会跳过并显示原因。
- **本地优先与缓存**：复用 OCR 进程，支持任务取消及检查点继续；视觉模型作为可选局部复核。

| 乐器 | 可选调弦（低弦 → 高弦） |
| --- | --- |
| 四弦贝斯 | 标准 E A D G、全降半音、全降全音、Drop D、Drop C |
| 五弦贝斯 | 标准 B E A D G、全降半音、全降全音、Drop A |

六弦吉他、多声部指弹不属于本版已完成支持范围。原项目的视频抽帧、PDF 导出等工具保留在旧界面 `/?legacy=1`，新旧版本编辑数据独立，不是同步编辑器。

## 请确认下载的是新版

从 **[Latest 发布页](https://github.com/Bionysus-bot/video-tab-to-gp5/releases/latest)** 下载 `video-tab-to-gp5-web.zip`，不要使用旧版 v0.1.1 的包。新版打开后应是暖白浅蓝的三步工作区，页脚显示 **v0.3.0**；若仍是深色单列页面，请确认启动的是新解压目录、地址没有 `?legacy=1`，并用 Ctrl+F5 刷新。先停止旧服务，再启动新目录的服务，避免访问旧端口。

## 下载哪个包

Windows 桌面版已完成本机安装、窗口启动、PDF → GP5 和退出验证，150 项后端测试通过。桌面安装包暂存于 **Release 草稿**，尚未公开下载：FFmpeg 主源码已归档，完整依赖源码与原构建材料仍需补齐，详见 [源码材料状态](docs/FFMPEG_SOURCE_STATUS.md)。下表仍为已公开的网页版包。

桌面包准备好后，Windows 10/11 x64 用户可选择安装包（双击安装，默认创建桌面快捷方式）或便携包（完整解压，运行 `PuJian.exe`，保留 `_internal`）。不需要另装 Python、Node.js、OCR 或 FFmpeg；WebView2 为必要组件，Ollama 仅用于可选复核。安装与数据目录、升级及排错见 [桌面版说明](docs/DESKTOP.md)。

在 [Releases](https://github.com/Bionysus-bot/video-tab-to-gp5/releases/tag/v0.3.0) 下载：

| 文件 | 适用场景 |
| --- | --- |
| `video-tab-to-gp5-web.zip` | 推荐本机使用，已含构建好的前端；仍需 Python 3.12、后端依赖和 FFmpeg，无需 Node.js |
| `video-tab-to-gp5-source.zip` | 二次开发，需自行安装 Node.js 并构建前端 |
| `SHA256SUMS.txt` | 核对两个 ZIP 的校验值 |

这两个包均不包含 Python 运行时、OCR 模型下载缓存、用户视频 / PDF / GP5、项目数据或密钥。GitHub 自动生成的 Source code 包同样需要自行构建前端。

## Windows 快速启动（推荐已构建前端包）

准备 Python **3.12**、FFmpeg（含 `ffprobe`）。安装 Python 时启用启动器并加入 PATH；安装 FFmpeg 后重新打开终端。

```powershell
winget install --id Gyan.FFmpeg -e
py -3.12 --version
ffmpeg -version
ffprobe -version
```

解压 `video-tab-to-gp5-web.zip`，在解压出的 `video-tab-to-gp5` 目录打开 PowerShell：

```powershell
py -3.12 -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install --upgrade pip
./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
powershell -ExecutionPolicy Bypass -File ./start.ps1 -Port 8001
```

看到 `Running: http://127.0.0.1:8001` 后，打开 **<http://127.0.0.1:8001/>**。首次安装依赖、初始化 OCR 可能需要网络。

日常使用只需启动，不必重新安装：

```powershell
# 启动
powershell -ExecutionPolicy Bypass -File ./start.ps1 -Port 8001
# 停止
powershell -ExecutionPolicy Bypass -File ./stop.ps1
```

服务后台运行；关机或重启后需要再次启动。若提示已有服务运行，请访问输出中的实际地址；不同端口不能共用同一份运行记录。

### 从源码安装

安装 Node.js 22 / 24 和 Git，然后执行：

```powershell
git clone --branch v0.3.0 --single-branch https://github.com/Bionysus-bot/video-tab-to-gp5.git
cd video-tab-to-gp5
py -3.12 -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ..
powershell -ExecutionPolicy Bypass -File ./start.ps1 -Port 8001
```

macOS / Linux 的手动启动方法见 [开发说明](docs/DEVELOPMENT.md)，尚未完成与本机 Windows 相同的安装验收。

## 使用：三步转谱

### 1. 准备素材

1. 点击 **导入视频 / pdf**，选择本地视频或不超过 50 MB 的 PDF。重新导入会建立独立项目。
2. 在清晰画面中框选谱面；可修改起点、宽度、高度并应用。联合谱必须包括上方五线谱、下方全部 TAB 弦线和小节编号。
3. 选择纯 TAB 或五线谱＋TAB，再选四弦 / 五弦贝斯、调弦方案及速度。速度和调弦使用设置值，不能凭截图缺失的信息自动还原。
4. 视频帧率和开始时间在 **设置 → 视频** 中调整。PDF 选区按第一页比例应用于所有页，混合版式请分项目导入。

### 2. 自动识谱

点击 **开始自动识谱**，程序整理谱行、本地识别、校验并生成草稿；有条件时进行原视频补读及可选局部模型复核。可以切换视图、取消任务，或在有检查点时继续。

草稿不以置信度低为由整体禁用下载。已知音符尽量保留，缺失小节或不确定拍位有明确标注；局部候选不是已确认音符。纯 PDF 没有对应视频帧时不能从视频补读。

### 3. 结果校对

- 按疑点选择小节，对照原图修改品位、弦号、时值、休止、延音等。弦号 1 是图中最上方的弦；第五弦是标准五弦贝斯最低音弦。
- **保存修改**会另存一个版本。切换小节、项目或版本时，未保存的修改会提示处理。
- 核对完成后点击 **保存并确认此小节**，或 **确认全部 · N**；批量范围是当前版本全部未确认小节，不受左侧筛选影响。
- 已确认小节在新 GP5 中不再显示核对文字；拍数错误、缺少音符或结构冲突的小节会保留标注并提示原因。再次编辑会取消该小节的确认状态。
- 下载新草稿到 Guitar Pro 播放核对。已下载的旧 GP5 不会被追溯修改。

含第五弦音符的乐谱切回四弦会被阻止，避免丢音。调弦或弦数变更会撤销设置确认，保存后按需重新确认。

## 可选视觉模型

无需模型也可使用本地识谱。在 **设置 → 模型** 启用局部复核，例如本机 Ollama 非思考视觉模型：

```powershell
ollama pull qwen3-vl:8b-instruct
```

运行 Ollama，填写地址 `http://127.0.0.1:11434`、模型 `qwen3-vl:8b-instruct`，再检测本地模型。模型失败或超时会保留疑点，不能保证自动修好每个音符。

兼容图片接口使用 `TAB_VISION_API_KEY` 启动环境变量提供密钥，不自动加载 `.env`。**启用远程服务会把谱面图片发送到该服务。**

## 数据备份与升级

- 用户素材与数据：`storage/projects/`，新版结果、任务、GP5 和版本在项目 `score/v2/` 下。
- 旧流程数据：项目 `score/score.json` 等，旧工具不会同步修改新版结果。
- 后台日志：`.runtime/server.log`、`.runtime/server-error.log`。

升级前停止服务、备份整个 `storage/projects/`。建议将新包解压到新目录，安装依赖后复制备份的 `storage/projects/`，再启动；不要删除原目录或覆盖外部人工修正的 GP5。旧数据首次进入新版会作为独立版本导入，Guitar Pro 外部修改不会自动同步回来。

若需回退代码，保留数据备份并使用旧发布包；旧界面不能读取所有新版版本数据。请勿同时启动两个服务写入同一数据目录。

## 验证与限制

本机完整回归 **148 项通过**，前端类型检查及构建通过。实际测试了 PDF → 3 小节 / 19 音符草稿、调弦保存、批量确认、版本回退和 GP5 回读；五弦合成 TAB 用真实 OCR 读出最低弦 4 个音符，并验证第五弦编辑及导出。[功能测试记录](docs/FUNCTIONAL_TEST_2026-10-24.md) · [五弦验证范围](docs/FIVE_STRING_BASS.md)

- 五弦联合谱包含合成图与 OCR 桩测试，仍需不同字体和真实整曲验收；未宣称所有曲谱达到同样准确度。
- 模糊、手写、遮挡、缺少节奏、复杂多声部、反复展开和跨图缺失弧线不保证识别。
- 全新机器安装、真实视觉模型效果及 Guitar Pro 整曲逐音听奏尚未完成本版全面验收。
- 当前输出单个贝斯音轨、`.gp5` 格式；可在 Guitar Pro 中另存新版 `.gp`，不直接写出 `.gtp` 或新版 `.gp`。标题建议使用英文。

## 常见问题

| 问题 | 处理 |
| --- | --- |
| 页面打不开 | 运行 `start.ps1 -Port 8001`，以启动输出的地址为准；重启电脑后需再次启动 |
| 找不到 FFmpeg / FFprobe | 安装后重开终端，检查两条 `-version` 命令 |
| Python 依赖安装失败 | 确认使用 Python 3.12，换新虚拟环境安装固定依赖 |
| 前端不存在 / 修改没生效 | 源码安装需 `npm ci`、`npm run build`；发布的 web 包已有前端，刷新页面即可 |
| 小节遗漏或标注多 | 检查完整弦线、编号、符尾及截图边界；草稿可先下载，标注不代表整小节都错 |
| 确认被跳过 | 展开跳过原因，修正拍数、缺失音符或延音对应后再次确认 |

## 开发与打包

```powershell
cd backend
./.venv/Scripts/python.exe -m unittest discover -s tests -q
cd ../frontend
npm ci
npm run build
cd ..
./backend/.venv/Scripts/python.exe scripts/package.py
./backend/.venv/Scripts/python.exe scripts/package.py --include-web
```

产物位于 `.release/`。设计文档：[PRD](docs/PRD.md)、[技术设计](docs/TECHNICAL_DESIGN.md)、[UI 设计](docs/UI_DESIGN.md)、[开发计划](docs/DEVELOPMENT_PLAN.md)。

## 项目来源、许可与版权

基于 [codemanhr/guitar-score-extractor](https://github.com/codemanhr/guitar-score-extractor) 二次开发。上游提供视频抽帧、区域选择、去重和 PDF 导出；本项目新增截图 / PDF 识谱、复核、版本化乐谱编辑、GP5 导出、新工作区及五弦支持。[来源说明](docs/UPSTREAM.md) · [上游 MIT 许可](LICENSES/UPSTREAM-MIT.txt)

**禁止商业用途的范围：**自 v0.1.1 起新授权、且发布者有权许可的原创新增内容，未经相应权利人书面许可，不得用于收费转谱、收费 API / SaaS、商业产品或其他变现服务。[项目许可](LICENSE) · [版权与使用说明](docs/COPYRIGHT.md)

上游 MIT、历史已按 MIT 发布的内容和第三方依赖保留原有权限，不追溯撤销。中文字体 [Fusion Pixel](https://github.com/TakWolf/fusion-pixel-font) 独立遵循 SIL OFL 1.1，许可及上游声明保存在 [LICENSES/fusion-pixel](LICENSES/fusion-pixel/)。GP5 写入使用 [PyGuitarPro](https://github.com/Perlence/PyGuitarPro)，OCR 使用 [RapidOCR](https://github.com/RapidAI/RapidOCR)。

请只处理有权使用的视频和曲谱。非商业使用、格式转换均不会自动取得原作品的复制、改编、传播或销售授权。本项目不把用户素材纳入软件许可或发布包。
