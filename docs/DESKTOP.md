# Windows 桌面版（本机测试版）

独立分支 `codex/windows-desktop`，网页版入口与识谱算法保留。仅桌面启动时设置独立数据目录和前端资源目录；普通网页版仍使用原有路径。

## 使用

- 安装包：`PuJian-0.3.0-Windows-x64-Setup.exe`，安装到当前用户目录，无需管理员权限。
- 或解压便携包，双击 `PuJian.exe`，必须保留同目录 `_internal` 文件夹。
- 包内包含 Python、OCR 模型、前端及 FFmpeg / FFprobe；用户无需安装 Python、Node.js 或 FFmpeg。
- 需要 Windows 10/11 x64 与 Microsoft Edge WebView2 Runtime。多数当前 Windows 已有此组件，缺失时从微软官网安装：https://developer.microsoft.com/microsoft-edge/webview2/ 。Ollama 仍为可选且不随包提供。
- 关闭窗口会结束本次后台和识谱任务，保留已写入的草稿与检查点。再次打开可继续已有任务。

## 数据

默认 `%LOCALAPPDATA%/PuJian/`，包含 `storage/projects/`、`webview/`、`desktop.log`、`backend.log`。程序安装目录与数据目录分开，普通升级 / 卸载不清除曲谱。备份请复制整个数据目录，旧网页版资料不会被自动移动或覆盖。

后台仅监听随机的 127.0.0.1 端口，桌面会话需要随机认证 Cookie，避免本机其他网页无凭据调用接口；不开放公网。重复启动给出提示。

## 构建

在完成网页版前端构建后：

```powershell
./backend/.venv/Scripts/python.exe -m pip install -r desktop/requirements.txt
./backend/.venv/Scripts/python.exe scripts/build_desktop.py --iscc "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"
# 没有 Inno Setup 时省略 --iscc，仍会生成便携 ZIP。
```

输出在 `output/desktop/`。构建脚本自动收集许可证、打包便携 ZIP 并生成 SHA256SUMS.txt。仅变更说明文件时，可用 `--skip-freeze` 复用已构建的程序。

### 启动故障排查

截图中的 GBK 编码错误来自无控制台运行时的日志编码，已改为 UTF-8。随后出现的后台超时来自打包遗漏 Python 运行时所需的证书资源，已一并补齐。桌面本机请求绕过系统代理，后台启动错误写入日志后直接退出；关闭窗口后会停止后台。

若仍无法打开，请查看 `%LOCALAPPDATA%/PuJian/desktop.log` 和 `backend.log`；非常早期的启动错误也会记录在 `process.log`。更新时安装修复版或完整解压新的便携包，不要仅替换单个 EXE。

### 自检

```powershell
./output/desktop/PuJian/PuJian.exe --smoke-test --data-dir .runtime/desktop-smoke
./output/desktop/PuJian/PuJian.exe --window-test --data-dir .runtime/desktop-window
```

第一项实际创建五弦 TAB 测试 PDF，识谱并下载 GP5，再读回验证弦号和品位；成功会保存 `smoke-result.json`。第二项打开 WebView2 窗口并检查工作区完成渲染，成功会保存 `window-result.json`。测试数据保留在指定目录，不会写入网页版项目。

2026-10-24 本机验证：150 项后端测试通过；清空开发工具 PATH 后，打包 EXE 完成 PDF → GP5，读回得到第五弦的四个 7 品音；WebView2 工作区渲染与正常退出通过。安装包还会在独立测试目录安装后再次执行识谱自检。

当前为本机验收构建，不自动上传 GitHub、不替换 v0.3.0 网页版 Release。公开再分发前还需补齐 FFmpeg 及其外部库对应源代码 / 构建材料，并在未安装开发环境的新机器验收。此测试包暂未进行代码签名。详见 `desktop/THIRD_PARTY.md`。
