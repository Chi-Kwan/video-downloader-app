# Video Downloader v0.1.0

首个公开版本。

## 主要功能

- Windows 图形界面，可粘贴完整分享文案或直接视频链接。
- 支持 yt-dlp 可解析的公开站点，并对抖音、B 站和小红书分享链接进行了针对性处理。
- 小红书手机端 `xhslink.cn` 短链可自动转换为笔记地址。
- 遇到需要页面验证的站点时，使用独立 WebView2 会话，不自动读取本机浏览器 Cookie。
- 默认选择当前访问条件下的最佳音视频流，也可限制为最高 1080P 或 720P。
- 当站点将高清视频和音频分开提供时，程序使用独立 FFmpeg 合并为一个 MP4。

## 系统要求

- Windows 10/11 x64。
- 建议安装 Microsoft Edge WebView2 Runtime；Windows 11 通常已预装。
- 首次需要合并分离音视频且系统未安装 FFmpeg 时，程序需联网下载并校验固定的上游 FFmpeg 7.1 构建。

## 完整性校验

下载后请用 Release 附件中的 `SHA256SUMS.txt` 核对 EXE。
