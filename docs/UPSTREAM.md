# 来源与二次开发说明

## 上游项目

- 名称：Guitar Score Extractor
- 作者 / 仓库所有者：GitHub 用户 [codemanhr](https://github.com/codemanhr)
- 仓库：<https://github.com/codemanhr/guitar-score-extractor>
- 本地二次开发的起点：[`cba82b252a65cae5b49b814f0ba07d0ae24310b0`](https://github.com/codemanhr/guitar-score-extractor/commit/cba82b252a65cae5b49b814f0ba07d0ae24310b0)
- 上游许可：MIT；原始版权声明 `Copyright (c) 2024 Guitar Score Extractor` 完整保留在根目录 `LICENSE`。

本项目是基于该版本的独立二次开发，不是上游官方发布。为避免将本地依赖、处理素材和运行记录带入公开仓库，发布仓库采用整理后的源码快照，不复制上游已有的依赖与素材历史。来源和基准提交在此保留，便于追溯。

## 沿用的基础能力

React / TypeScript 页面与 FastAPI 后端框架，以及视频上传和预览、ROI 框选、FFmpeg 抽帧、图像预处理、滚动或相似画面去重、A4 PDF 排版导出及进度展示。

对应主体包括 `backend/app/api/routes.py`、原有视频 / 图像 / PDF 服务、`frontend/src/pages/Workspace.tsx` 与原有前端组件。这些模块并非本次从零编写。

## 本次在其基础上增加的能力

| 部分 | 主要文件 | 用途 |
| --- | --- | --- |
| 截图 / PDF 输入整理 | `score_images.py` | PDF 渲染、TAB 弦线定位、谱行筛选及来源记录 |
| 本地 TAB 读取 | `local_tab_reader.py` | 几何分析、品位 OCR、节奏及部分演奏符号识别 |
| 视觉模型适配 | `tab_recognizer.py` | Ollama 非思考视觉模型及兼容接口、输出校验和异常提示 |
| 乐谱数据模型 | `models/score.py` | 小节、拍位、音符、调弦、效果与人工核对状态 |
| GP5 生成与校验 | `score_exporter.py` | 时值 / 延音 / 编号检查，草稿和已核对版本导出 |
| 转谱接口 | `api/score_routes.py` | 任务进度、逐行保存、核对结果保留、可撤销跳过谱行 |
| 转谱编辑页面 | `ScorePanel.tsx` | 原图对照、音符及效果编辑、JSON 编辑、导出 |
| Windows 兼容 | `image_io.py`、图像 / PDF 服务调整 | 中文路径读写和本机运行 |
| 本机运行与发布 | `start.ps1`、`stop.ps1`、`scripts/package.py` | 后台运行、日志、干净源码及网页构建包 |

还增加了页面恢复最近项目、GP5 二进制读回校验测试，以及与用户已确认片段比较的本地回归测试。公开包不包含用户提供的视频、原曲谱或其转谱文件；公开测试使用合成图像、手工构造数据与接口模拟。

## 依赖致谢

- [FFmpeg](https://ffmpeg.org/)：视频处理，需用户单独安装。
- [OpenCV](https://opencv.org/)：谱面几何与图像处理。
- [RapidOCR](https://github.com/RapidAI/RapidOCR)：数字 OCR，通过 `rapidocr-onnxruntime` 使用。
- [pypdfium2](https://github.com/pypdfium2-team/pypdfium2)：PDF 页面渲染。
- [PyGuitarPro](https://github.com/Perlence/PyGuitarPro)：GP5 读写。
- [Ollama](https://ollama.com/)：可选本地视觉模型运行服务。

依赖和模型各自的许可不由本项目 MIT 许可替代。发布包只包含本项目源码和可选前端构建产物，不捆绑 FFmpeg、Python、Node.js 或 Ollama 模型。
