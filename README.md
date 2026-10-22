# Video TAB to GP5 · 视频曲谱转 Guitar Pro

把视频里的动态 TAB 谱提取成 PDF，再把截图或已有 PDF 转成可编辑的 Guitar Pro 5（`.gp5`）文件。适用于吉他、贝斯的数字指法谱，提供本地识谱、人工校对和导出。

**非商业使用：自 v0.1.1 起新授权的原创新增内容禁止用于商业用途，未经相应权利人书面许可，不得用于收费转谱、商业产品或变现服务。** 上游及已按 MIT 发布的内容保留原许可，本声明不追溯取消其既有权限。完整适用范围见 [LICENSE](LICENSE) 和 [版权与使用说明](docs/COPYRIGHT.md)。

**曲谱、视频版权：**请仅处理你有权使用的素材；转换成 PDF / GP5 不会自动取得原作品的传播、改编或销售授权，非商业使用也不当然免除版权义务。

**项目来源：**本项目基于 [codemanhr/guitar-score-extractor](https://github.com/codemanhr/guitar-score-extractor) 二次开发。原项目提供视频抽帧、谱面区域选择、去重和 PDF 导出；本项目在此基础上增加了 **PDF / 截图识谱 → 乐谱编辑 → GP5 导出**。原项目 MIT 许可和版权声明保留在 [LICENSES/UPSTREAM-MIT.txt](LICENSES/UPSTREAM-MIT.txt)，详细来源见 [来源与致谢](docs/UPSTREAM.md)。

当前定位是辅助转谱工具，需要对照原图检查结果。输出格式是 **`.gp5`**，可用 Guitar Pro 打开、播放、编辑，并另存为新版 `.gp`；目前不直接写出新版 `.gp` 或旧版 `.gtp`。

## 能做什么

| 功能 | 来源 / 当前状态 |
| --- | --- |
| 上传视频、预览、框选谱面、按时间范围抽帧 | 沿用原项目 |
| 相似帧去重、整理 A4 PDF、查看处理进度 | 沿用原项目，补充 Windows 路径兼容 |
| 从当前视频截图或外部 PDF 整理 TAB 谱行 | 新增；识别 4～6 根弦线，过滤无谱面图片 |
| 读取品位、节奏、休止、延音、闷音和部分演奏符号 | 新增；优先使用 OpenCV + RapidOCR，也可使用视觉模型 |
| 对照原图编辑小节、音符、时值和演奏属性 | 新增；可视化编辑及高级 JSON 编辑 |
| 小节拍数检查、未识别项检查、人工核对标记 | 新增；存在结构错误时阻止导出 |
| 下载 GP5 草稿 / 已核对 GP5 | 新增；使用 PyGuitarPro 生成文件 |
| 保留已核对谱行、手动跳过重复或片尾谱行 | 新增；跳过可撤销，原图保留 |
| Windows 后台启动、停止、日志和页面状态恢复 | 新增 |

## 先准备运行环境

推荐 **Windows 10 / 11 + Python 3.12 + Node.js 22 或 24 + FFmpeg**。本项目已在 Windows、Python 3.12、Node.js 24 环境验证。macOS / Linux 可按下文手动启动，尚未完成同等环境验证。

- [Python 3.12](https://www.python.org/downloads/)：安装时勾选加入 PATH。当前依赖固定版本，请先使用 3.12。
- [Node.js](https://nodejs.org/)：用于安装和构建前端。
- [FFmpeg](https://ffmpeg.org/download.html)：需要 `ffmpeg`、`ffprobe` 都能在终端执行。即使只导入 PDF，当前服务启动时也会检查两者。
- [Git](https://git-scm.com/downloads)：用于克隆代码；也可直接下载源码 ZIP。
- Ollama **可选**：本地规则支持的谱面不需要安装视觉模型。

Windows 可用以下命令安装 FFmpeg，然后重新打开终端：

```powershell
winget install --id Gyan.FFmpeg -e
```

安装后检查：

```powershell
py -3.12 --version
node --version
npm --version
ffmpeg -version
ffprobe -version
```

## Windows 安装与启动

在 PowerShell 中逐行运行：

```powershell
git clone https://github.com/Bionysus-bot/video-tab-to-gp5.git
cd video-tab-to-gp5

py -3.12 -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install --upgrade pip
./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt

cd frontend
npm ci
npm run build
cd ..

powershell -ExecutionPolicy Bypass -File ./start.ps1
```

看到 `Running: http://127.0.0.1:8000` 后，在浏览器打开 **<http://127.0.0.1:8000/>**。

服务在后台运行，关闭终端后仍可访问；电脑重启后需要再次启动。日常启动无需重新安装依赖或构建：

```powershell
# 启动
powershell -ExecutionPolicy Bypass -File ./start.ps1

# 停止
powershell -ExecutionPolicy Bypass -File ./stop.ps1

# 8000 端口被占用时
powershell -ExecutionPolicy Bypass -File ./start.ps1 -Port 8001
```

从 [Releases](https://github.com/Bionysus-bot/video-tab-to-gp5/releases) 下载 `video-tab-to-gp5-web.zip` 时，包内已包含构建好的页面：解压后安装 Python 依赖、FFmpeg，直接运行 `start.ps1` 即可，**可跳过 Node.js 和前端构建**。`source.zip` 和 GitHub 的 Source code 压缩包则需要执行完整构建步骤。

## 使用方法

### 方式一：从视频开始

1. 打开页面，上传本地视频。
2. 预览到谱面清晰的位置，框选完整的 TAB 区域。保留小节线、数字、符干和符尾，不要只截弦线中间的一条窄带。
3. 设置开始 / 结束时间和采样帧率，点击 **开始处理**。可先用较短片段确认裁切结果。
4. 完成后可下载 PDF。需要继续转谱时，在 **转换为 Guitar Pro 谱** 区域点击 **读取当前视频截图**。
5. 检查每行原图和过滤结果，再按下面的识谱流程操作。

### 方式二：已有 PDF

无需上传视频。在 **转换为 Guitar Pro 谱** 区域点击 **导入 PDF**，选择不超过 **50 MB** 的 PDF，然后检查整理出的谱行。

视频截图和 PDF 是两种输入方式，任选一种即可。重新导入 PDF 或重新读取截图会重建谱行、清空该项目现有转谱数据；重要结果请先下载或备份。

### 识谱、校对与导出

1. **选乐器、填速度。** 默认是四弦贝斯标准调弦；吉他可切换为六弦。默认速度 `120` 是占位值，需改成实际 BPM。特殊调弦在高级数据中修改，按最高音弦到最低音弦填写 MIDI 音高。
2. **先试少量谱行。** 保持默认的本地优先策略，先识别前 3 行；效果合适后再提高行数。这里的数字表示“从开头处理前几行”，不是“接着处理几行”。
3. **对照原图修改。** 检查弦号、品位、时值、休止、延音与演奏属性。`4` 表示四分音符、`8` 表示八分音符；空音符列表表示休止；弦号 `1` 是图中最上方的弦。
4. **保存并校验。** 查看拍数不符、未知音符、延音关系等提示，修正后再次保存。当前本地读取的小节编号按画面顺序暂定，拍号暂按 `4/4`，都需要核对。
5. **先下载草稿试听。** 拍数等结构检查通过、速度和调弦已确认后，可点击 **下载 GP5 草稿（供核对）**，在 Guitar Pro 中检查。草稿不会自动标记为已核对。
6. **逐小节确认。** 对照原图检查无误后，勾选对应小节的核对标记，再保存；所有小节通过校验并核对后，可下载已核对 GP5。

仅勾选核对标记不会修复识别错误。程序不会为了凑满一小节而自动补音、补休止；未识别的音高、时值及拍数错误会阻止草稿和正式导出。

### 重复画面和重新识别

- 视频帧去重主要用于 PDF 整理；识谱阶段不会因为两段旋律相同就删除其中一段。
- 明确是重复画面、片尾静止页时，可手动跳过该谱行并填写原因；可随时恢复。
- 一行中只要有一个小节已核对，重新识谱会保留整行，包括该行尚未核对的手工修改。想重新识别这一行，先取消该行所有小节的核对标记并保存。
- 跳过含已核对小节的谱行前，也需要先取消该行核对标记。

## 可选：使用 Ollama 视觉模型

当本地读取不支持某种谱面布局时，可使用本机视觉模型。安装并运行 [Ollama](https://ollama.com/)，下载明确的非思考版本：

```powershell
ollama pull qwen3-vl:8b-instruct
ollama list
```

如果 Ollama 没有运行，先启动 Ollama 应用，或在单独终端运行 `ollama serve`。模型下载需要网络及足够的磁盘、内存；运行速度取决于本机硬件。

页面中填写：

| 项目 | 值 |
| --- | --- |
| 服务 | Ollama |
| 接口地址 | `http://127.0.0.1:11434` |
| 视觉模型 | `qwen3-vl:8b-instruct` |
| 策略 | 默认本地优先；需要比较模型效果时切换为视觉模型 |

点击 **检测本地模型**，确认模型支持图片输入。遇到持续思考、没有答案时，先核对完整模型名包含 `instruct`。模型正常返回也可能识别出 0 小节；请检查完整小节、清晰度和符尾是否保留，必要时换模型或手工编辑。

也支持接收图片的 OpenAI 兼容接口：选择兼容服务，填写含 `/v1` 的 API 地址和模型名。密钥从启动服务的环境变量 `TAB_VISION_API_KEY` 读取；不会从 `.env` 自动加载。**使用远程兼容接口时，所处理的谱行图片会发送给该服务。**

## 当前识别范围与限制

- 本地识别针对清晰、水平排列、弦距较均匀的 4～6 弦 TAB，主要围绕四弦贝斯素材验证。六弦或其他排版需要另行检查。
- 已处理的符号包括品位数字、X 闷音、常见时值与休止、附点、断奏、括号延音、部分滑音 / 连奏滑音 / 滑出、击勾弦和倚音。能保存某项演奏属性，不代表所有字体和布局都能自动识别。
- 倚音时值看不清时，暂用拍外 32 分倚音并提示人工确认。三连音可在结构化数据中表达，自动识别不作准确率保证。
- 手写谱、模糊或遮挡、缺少节奏信息、复杂多声部、跨行残缺小节、复杂反复记号展开暂不保证。
- 不能从没有标注的截图可靠还原调弦、速度，不能仅凭 PDF 证明视频中的所有小节都已提取。源素材完整性仍需人工检查。
- 目前导出单个吉他 / 贝斯音轨；GP5 标题采用西文编码，建议使用英文标题。
- 此工具读取画面中已有的谱，不做音频听写。

## 数据、日志和备份

| 路径 | 内容 |
| --- | --- |
| `storage/projects/<项目ID>/` | 上传视频、截图、PDF 和项目配置 |
| `storage/projects/<项目ID>/score/` | `manifest.json`（谱行）、`score.json`（可编辑谱）、`task.json`（进度）和 GP5 |
| `.runtime/server.log` | Windows 后台运行日志 |
| `.runtime/server-error.log` | Windows 后台错误日志 |

备份时复制整个 `storage/projects/`。浏览器会记住最近的项目 ID。仓库与发布包不包含用户视频、曲谱或运行数据。

## 常见问题

| 现象 | 操作 |
| --- | --- |
| PowerShell 禁止运行脚本 | 使用上文 `powershell -ExecutionPolicy Bypass -File ...`，无需永久修改系统策略 |
| 找不到 `py` | 安装 Python 3.12 和启动器，或确认 `python --version` 为 3.12 后将 `py -3.12` 换成 `python` |
| `pip` 安装失败或要求编译 NumPy | 检查使用的是 Python 3.12；若环境用错，换一个新目录按安装步骤重建虚拟环境 |
| 缺少 FFmpeg / FFprobe | 安装后重开终端，确认两条 `-version` 命令都能执行 |
| 8000 端口被占用 | 启动时加 `-Port 8001`，访问日志显示的新地址 |
| 页面空白、构建产物不存在 | 在 `frontend` 中运行 `npm ci`、`npm run build`，再重启服务 |
| 没有检测到 Ollama | 本地支持的谱面仍可先识别；需要模型时启动 Ollama 并检查 11434 端口 |
| 识别 0 小节 / clipped measure | 查看原图是否含完整小节线、数字和符尾；先试一行，检查裁切或换模型 |
| GP5 下载按钮不可用 | 先保存修改、确认速度调弦，处理校验错误；正式版还需要核对全部小节 |
| 中文标题导出失败 | 将乐谱标题改成英文后保存 |
| 改了前端代码却没变化 | 重新 `npm run build`，停止并启动服务，然后刷新页面 |

## 开发、测试与打包

后端测试使用标准库 `unittest`，无需额外安装测试框架：

```powershell
cd backend
./.venv/Scripts/python.exe -m unittest discover -s tests -v
cd ../frontend
npm run build
cd ..
```

生成干净的源码 ZIP 和包含已构建页面的 ZIP：

```powershell
./backend/.venv/Scripts/python.exe scripts/package.py
./backend/.venv/Scripts/python.exe scripts/package.py --include-web
```

产物在 `.release/`。详细目录、开发模式、macOS / Linux 启动方法和测试说明见 [开发说明](docs/DEVELOPMENT.md)，版本变化见 [CHANGELOG](CHANGELOG.md)。

## 许可与致谢

本仓库采用分范围许可：自 v0.1.1 起首次发布、且发布者有权许可的原创新增内容使用 [自定义非商业许可](LICENSE)；上游 MIT 代码和已按 MIT 发布的历史内容保留原有权限。带商业用途限制的部分属于源码公开项目，不宣称采用 OSI 开源许可，不能把整个仓库简单视为全部 MIT 或全部禁止商业使用。

请勿将受非商业条款约束的内容用于付费转谱、收费 API / SaaS、广告变现服务或商业产品，除非另获相应权利人书面授权。对输入作品和转换结果，仍须独立确认复制、改编与传播权限。完整说明及版权反馈渠道见 [版权与使用说明](docs/COPYRIGHT.md)。

视频转截图 / PDF 的基础来自 [codemanhr/guitar-score-extractor](https://github.com/codemanhr/guitar-score-extractor)，保留其 `Copyright (c) 2024 Guitar Score Extractor` 声明；GP5 写入使用 [PyGuitarPro](https://pyguitarpro.readthedocs.io/)，本地 OCR 使用 [RapidOCR](https://github.com/RapidAI/RapidOCR)。依赖和模型遵循各自许可；输入曲谱、视频及其中作品不属于本项目软件许可的授权范围。
