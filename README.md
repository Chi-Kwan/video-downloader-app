# Video Downloader

Windows 图形界面多平台视频下载器。支持粘贴分享文案或直接链接、选择保存目录、画质上限和独立站点会话。源码入口是 `app.py`。

## 从源码运行

需要 Windows 10/11 和 Python 3.12：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

内置登录窗口使用 Microsoft Edge WebView2 Runtime。Windows 11 通常已预装；若系统没有，需从 Microsoft 安装 WebView2 Runtime。

## 构建单文件 EXE

在仓库根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-exe.ps1
```

生成文件：`dist/VideoDownloader.exe`。构建依赖已在 `requirements.txt` 锁定版本。

## 画质与 FFmpeg

默认的“最佳画质”会选择当前访问条件下站点提供的最佳视频和音频流。登录、地区、会员权限和站点接口都可能影响可用画质。

FFmpeg **不包含在本仓库或发布的 EXE 中**。需要合并分离的高清音视频时，程序优先使用系统 FFmpeg；若未安装，会从上游发布页下载固定的 FFmpeg 7.1 构建、校验 SHA-256，并在本地保存其许可证和对应源码链接。详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可与使用边界

本项目源码使用 MIT License。EXE 内包含的第三方组件仍适用各自许可证，文本位于 `licenses/`。

仅处理你有权获取的公开内容。程序不绕过 DRM、付费或私密访问控制；使用者需遵守内容平台的服务条款和所在地法律。
