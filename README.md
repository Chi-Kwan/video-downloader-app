# Video Downloader

Windows 图形界面多平台视频下载器。支持粘贴分享文案或直接链接、选择保存目录、画质上限和独立站点会话。源码入口是 `app.py`。

目前只提供 Windows 10/11 x64 版本。普通用户直接下载 EXE，不用安装 Python，也不用打开黑色命令行窗口。

## 适合谁用

- 保存自己发布或已获授权的公开视频。
- 做视频剪辑、课件、资料整理或内容研究，需要将参考视频保存到本地。
- 不熟悉 yt-dlp、FFmpeg 和 Python，只想用图形界面操作的 Windows 用户。

这不是批量爬取或绕过平台权限的工具。付费、私密、DRM 保护或账号本身无权访问的内容不在支持范围内。

## 普通用户怎么下载

1. 打开 [Releases 下载页](https://github.com/Chi-Kwan/video-downloader-app/releases/latest)。
2. 找到页面下方的 **Assets**。
3. 下载 `VideoDownloader-v0.1.0-windows-x64.exe`。
4. 双击 EXE 即可运行。你可以把它放在桌面、U 盘或任意文件夹。

程序暂时没有付费代码签名证书，Windows 可能显示“Windows 已保护你的电脑”或“未知发布者”。请先确认文件来自本仓库的 Releases 页，再用 Release 中的 `SHA256SUMS.txt` 核对文件。确认无误后，可点“更多信息”和“仍要运行”。

PowerShell 校验命令：

```powershell
Get-FileHash .\VideoDownloader-v0.1.0-windows-x64.exe -Algorithm SHA256
```

## 第一次怎么用

1. 在视频 App 或网页中点“分享”和“复制链接”。
2. 打开视频下载器，点“粘贴链接”，或直接按 `Ctrl+V`。纯链接和包含标题、口令的整段分享文案都可以粘贴。
3. 第一次使用时下载目录为空。点“浏览”选择文件夹。程序会记住它，下次打开时自动恢复。
4. 选择画质。一般保持“最佳画质”即可；也可限制为最高 1080P 或 720P。
5. 点“开始下载”。日志区会显示进度和失败原因。
6. 看到“下载完成”后，点“打开目录”查看视频。

程序会自动从分享文案中提取网址。小红书手机端复制出来的 `xhslink.cn` 短链也会自动转换，不用先在浏览器里换成长链接。

## 支持哪些网站

| 站点 | 状态 | 说明 |
| --- | --- | --- |
| 抖音 | 已测试 | 支持公开视频和独立登录会话。平台风控可能要求重新验证。 |
| 哔哩哔哩 | 已测试 | 支持 `bilibili.com` 和 `b23.tv`。高画质可能需要对应账号权限。 |
| 小红书 | 已测试 | 支持笔记长链接和手机 App 分享短链。 |
| YouTube、微博、快手及其他公开站点 | 可尝试 | 底层使用 yt-dlp，但本项目没有逐一保证。 |

网站会修改页面和风控规则。今天能下载的链接，以后可能需要更新程序、登录或重新验证。

## 遇到登录窗口怎么办

程序先尝试直接下载公开视频。只有网站要求 Cookie、验证码或登录时，才会打开独立登录窗口。

1. 在弹出窗口中完成登录、扫码或页面验证。
2. 打开目标视频，确认它可以正常播放。
3. 点顶部的“我已登录，重新下载”。

下载器不会自动读取你平时使用的 Chrome 或 Edge Cookie。各网站的会话独立保存在本机，不要把数据文件夹发给别人。

## 程序数据和下载视频放在哪里

- 电脑有 D 盘时：程序数据放在 `D:\视频下载器数据`。
- 没有 D 盘时：放在 `%LOCALAPPDATA%\视频下载器数据`。
- 真正下载的视频放在你在界面中选择的目录。

数据目录保存上次选择的下载路径、站点会话和按需下载的 FFmpeg。在主界面打开“自动会话说明”，可查看数据位置或重置网站会话。

## 为什么下载时会出现两个文件

- `.part` 是正在下载的临时文件，成功后会改成正式文件名。
- 很多网站把高清画面和声音分成两路。程序会分别下载，再用 FFmpeg 合并成一个 MP4。完成后，临时文件会由 yt-dlp 清理。

如果系统没有 FFmpeg，程序在第一次需要合并时会自动下载固定版本并校验 SHA-256。FFmpeg 不封装在本项目的 EXE 里。

## 画质说明

“最佳画质”指当前链接、账号权限和地区条件下，网站提供的最佳音视频流。它不代表平台保存的最高母版，也不会把低清视频变成高清视频。进入内置浏览器备用流程后，某些站点只能取得播放器当前加载的清晰度。

## 常见问题

### 双击 EXE 没有反应

查看 Windows 安全中心或杀毒软件是否拦截了文件。只建议使用从本仓库 Releases 下载且 SHA-256 匹配的文件。

### 内置登录窗口打不开

该窗口使用 Microsoft Edge WebView2 Runtime。Windows 11 通常已预装；如果系统没有，请从 [Microsoft 官方页面](https://developer.microsoft.com/microsoft-edge/webview2/) 安装 Evergreen Runtime。它只是网页渲染内核，不要求你平时使用 Edge 浏览器。

### 日志显示 `Unsupported URL`

确认粘贴的是具体视频页，而不是搜索页、个人主页或话题页。分享文案中含有多个网址时，可以只保留目标视频链接后重试。

### 昨天能下载，今天失败

平台可能修改了接口、链接已失效、账号会话过期，或当前网络触发了风控。重新复制具体视频页的链接；如果弹出登录窗口，完成页面验证后再点重试。

### macOS、Linux 或手机能用吗

当前的 EXE 只能在 Windows 10/11 x64 上运行。图形界面和 WebView2 登录流程也是按 Windows 实现的。

## 这些 Python 文件是什么

仓库里有 5 个 Python 文件，它们共同组成一个程序：

- `app.py`：主程序、图形界面和下载流程。
- `browser_media.py`：在独立登录窗口中识别播放器媒体。
- `session_auth.py`：管理各网站的独立登录会话。
- `share_urls.py`：从分享文案提取网址并转换短链接。
- `ffmpeg_runtime.py`：查找、下载和校验 FFmpeg。

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
