# 视频下载器 v0.1.0

> **普通用户：在 Assets 里只需下载 `VideoDownloader-v0.1.0-windows-x64.exe`，双击就能使用。**

这是 Windows 图形界面版本。不用安装 Python，不用自己配置 yt-dlp，也不需要打开命令行。

## Assets 里应该下载哪个

| 文件 | 谁需要下载 | 用途 |
| --- | --- | --- |
| `VideoDownloader-v0.1.0-windows-x64.exe` | **普通用户** | 视频下载器主程序。下载后直接双击运行。 |
| `SHA256SUMS.txt` | 想校验文件的用户 | 记录 EXE 和许可证包的 SHA-256，用来确认文件没有下载损坏或被替换。 |
| `VideoDownloader-v0.1.0-licenses-and-notices.zip` | 开发者、分发者 | 第三方组件的许可证、组件清单和合规材料。普通使用不需要解压它。 |
| `Source code (zip)` / `Source code (tar.gz)` | 开发者 | GitHub 自动生成的源码压缩包。普通用户不要下载这两个。 |

## 最短使用步骤

1. 从 Assets 下载 EXE 并双击打开。
2. 把视频链接或 App 复制出来的整段分享文案粘贴进去。
3. 点“浏览”选择下载目录，画质一般保持“最佳画质”。
4. 点“开始下载”。完成后可直接打开保存文件夹。

第一次打开时，下载目录默认为空。选择一次后，程序会记住上次的位置。

## 支持范围

- 已针对性测试抖音、哔哩哔哩和小红书。
- 小红书手机端 `xhslink.cn` 短链可自动转换。
- 底层使用 yt-dlp，YouTube、微博、快手及其他公开站点也可尝试，但不做逐站保证。
- 付费、私密、DRM 保护或账号无权访问的内容不在支持范围内。

更完整的操作说明、登录流程和常见问题见[项目主页 README](https://github.com/Chi-Kwan/video-downloader-app#readme)。

## 登录和验证

公开视频会先尝试直接下载。如果网站要求登录、扫码或验证码，程序才会打开独立 WebView2 窗口。完成验证并打开目标视频后，点顶部的“我已登录，重新下载”。

该会话保存在本机，不会自动读取你平时使用的 Chrome 或 Edge Cookie。

## 系统要求

- Windows 10/11 x64。macOS、Linux 和手机不能直接运行这个 EXE。
- 内置登录窗口需要 Microsoft Edge WebView2 Runtime，Windows 11 通常已预装。
- 首次需要合并分离的高清画面和声音时，程序会按需下载并校验 FFmpeg 7.1。

## Windows 提示“未知发布者”

这个版本暂时没有付费代码签名证书。请确认文件从本页下载，并用 `SHA256SUMS.txt` 核对哈希。本版 EXE 的 SHA-256 是：

```text
b640c256bd8feb973bd60b3cf99ab7bd0ee3a61b363fde4be4d9c47016b78f1f
```

确认一致后，可在 Windows SmartScreen 中点“更多信息”和“仍要运行”。
