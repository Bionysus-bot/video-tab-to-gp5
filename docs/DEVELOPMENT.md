# 开发说明

日常安装和使用见根目录 [README](../README.md)。后端使用 Python 3.12，前端使用 Node.js 22 / 24。

## 目录

```text
backend/
  app/
    api/routes.py           视频与 PDF 接口（上游基础）
    api/score_routes.py     识谱、校对与 GP5 接口
    models/score.py         结构化乐谱
    services/score_images.py
    services/local_tab_reader.py
    services/tab_recognizer.py
    services/score_exporter.py
  tests/                    可公开的合成图像、接口及二进制测试
frontend/
  src/components/ScorePanel.tsx
  src/pages/Workspace.tsx
scripts/package.py          按允许清单生成发布 ZIP
docs/UPSTREAM.md            原项目来源及修改归属
storage/projects/           本机运行数据，自动创建，不进入发布包
.runtime/                   Windows 进程记录和日志，不进入发布包
.release/                   打包输出，不进入发布包
```

## 开发模式

完成 README 中的依赖安装后，分两个终端运行。先停止已有的 8000 端口服务。

Windows 后端（在项目根目录）：

```powershell
cd backend
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

前端（另一个终端，在项目根目录）：

```powershell
cd frontend
npm run dev
```

访问 <http://localhost:5173/>；Vite 将 `/api` 代理到 8000。默认前后端端口不同，开发模式修改后端端口时也需调整 `frontend/vite.config.ts`。

## macOS / Linux 手动运行

先安装 Python 3.12、Node.js 和 FFmpeg（例如 macOS 使用 `brew install ffmpeg`，Ubuntu 使用 `sudo apt install ffmpeg`），然后在项目根目录：

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci
npm run build
cd ../backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

访问 <http://127.0.0.1:8000/>，按 Ctrl+C 停止。这是前台运行方式。原项目的 `start.sh` / `stop.sh` 作为开发脚本保留，用于 5173 + 8000 双服务，不与 Windows 后台管理脚本混用。

服务面向本机使用，目前没有登录、权限或公开部署管理功能。

## 乐谱格式

下面是独立构造的一小节贝斯练习数据，不来自用户素材。每个拍位是一个四分音符；弦号按高音到低音排列，标准贝斯是 G2 / D2 / A1 / E1：

```json
{
  "title": "Four quarter notes",
  "instrument": "bass",
  "tempo": 100,
  "tuning": [43, 38, 33, 28],
  "settings_confirmed": true,
  "measures": [{
    "number": 1,
    "numerator": 4,
    "denominator": 4,
    "reviewed": false,
    "beats": [
      {"duration": 4, "notes": [{"string": 4, "fret": 0}]},
      {"duration": 4, "notes": [{"string": 4, "fret": 2}]},
      {"duration": 4, "notes": [{"string": 3, "fret": 0}]},
      {"duration": 4, "notes": []}
    ]
  }]
}
```

- `duration` 是音符分母，不是拍数；`dotted` 为附点，`triplet` 为三连音。
- `notes: []` 为休止；同一拍位内多个音符表示同时发声。
- `kind` 为 `normal` / `tie` / `dead`；延音应与前音匹配。
- `slide`、`legato_slide`、`slide_out`、`hammer`、`staccato`、`grace` 保存演奏属性。完整字段和约束以 `models/score.py` 为准。
- 未确认的音高 / 时值放在 `unresolved`，不会通过结构校验。
- 识别和编辑不等于人工确认，`reviewed` 需用户核对后设置。

## 转谱接口

服务运行时可访问 <http://127.0.0.1:8000/docs> 查看完整参数。以下路径均以前缀 `/api` 开始，`{id}` 是创建项目后取得的项目 ID。

| 方法和路径 | 用途 |
| --- | --- |
| `GET /score/models` | 检测本机 Ollama 模型和视觉能力 |
| `POST /projects/{id}/score/prepare` | 整理当前视频截图，重置现有转谱 |
| `POST /projects/{id}/score/pdf` | multipart 字段 `file` 上传 PDF，重置现有转谱 |
| `GET /projects/{id}/score` | 乐谱、谱行、任务、正式及草稿校验结果 |
| `PUT /projects/{id}/score` | 保存完整 Score JSON |
| `POST /projects/{id}/score/recognize` | 启动识谱；`max_rows` 为从开头处理的行数 |
| `GET /projects/{id}/score/rows/{filename}` | 查看原图 |
| `PUT /projects/{id}/score/rows/{filename}/exclude` | `excluded` 和 `reason`，跳过 / 恢复谱行 |
| `POST /projects/{id}/score/export-draft` | 结构校验通过后生成未全部核对的草稿 |
| `GET /projects/{id}/score/download-draft` | 校验并下载草稿 |
| `POST /projects/{id}/score/export` | 通过校验且全部核对后生成 GP5 |
| `GET /projects/{id}/score/download` | 校验并下载已核对 GP5 |

每行识别后保存进度。重新识别会保留含已核对小节的整行；任务中断不表示已经完成。下载时会重新校验，避免返回旧数据生成的文件。

兼容视觉接口的密钥使用环境变量设置，例如在启动 Windows 服务前：

```powershell
$env:TAB_VISION_API_KEY = '在本机填写你的密钥'
powershell -ExecutionPolicy Bypass -File ./start.ps1
```

若服务已经运行，先用 `stop.ps1` 停止，再从设置了变量的终端启动。不在代码或 API 地址中填写密钥。

## 测试

```powershell
cd backend
./.venv/Scripts/python.exe -m unittest discover -s tests -v
cd ../frontend
npm run build
```

公开测试覆盖合成谱面的弦线 / 小节线 / 休止识别、未知音符保护、拍数和延音检查、GP5 二进制读回、模型接口协议、人工核对保留和跳过谱行等。模型服务通过模拟响应验证，不需要 Ollama、远程 API 或密钥。OCR 权重由 Python 依赖包提供。

本地还有用户素材回归测试 `test_local_tab_reader_private.py` 和 `tests/fixtures/`，只用于比较用户确认的片段，均不进入公开仓库和 ZIP。公开测试不依赖这些文件；本地完整回归结果也不代表对任意曲谱的准确率保证。

## 打包与发布

先执行测试及 `npm run build`，在项目根目录：

```powershell
./backend/.venv/Scripts/python.exe scripts/package.py
./backend/.venv/Scripts/python.exe scripts/package.py --include-web
```

- `.release/video-tab-to-gp5-source.zip`：可构建源码，需安装 Python / Node.js 依赖并构建前端。
- `.release/video-tab-to-gp5-web.zip`：源码加 `frontend/dist/`，不需要 Node.js，仍需安装 Python 依赖和 FFmpeg。
- 两个 ZIP 都以 `video-tab-to-gp5/` 为顶层目录。
- 打包采用文件允许清单，包含 `LICENSE`、`LICENSES/UPSTREAM-MIT.txt`、`NOTICE` 和版权说明；不读取 `.git` 历史，不带虚拟环境、`node_modules`、用户数据、输出曲谱、密钥或私有回归素材。
- `.github/workflows/ci.yml` 在推送 / PR 时运行公开测试及前端构建。

源码 ZIP 可用于创建干净的新仓库。继续开发请基于新仓库，避免把原工作目录中历史跟踪的依赖或素材再次提交。分范围的软件许可、上游许可、版权与来源记录应随副本保留，详见 [版权说明](COPYRIGHT.md)。
