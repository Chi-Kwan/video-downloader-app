from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile


FFMPEG_VERSION = "7.1"
FFMPEG_ARCHIVE_URL = (
    "https://github.com/GyanD/codexffmpeg/releases/download/7.1/"
    "ffmpeg-7.1-essentials_build.zip"
)
FFMPEG_ARCHIVE_SHA256 = "fa7d4d7e795db0e2503f49f105f46ed5852386f0cfdd819899be3b65ebde24fc"
FFMPEG_EXE_SHA256 = "2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3"
FFMPEG_SOURCE_URL = "https://github.com/FFmpeg/FFmpeg/commit/b08d7969c5"
_PREFIX = "ffmpeg-7.1-essentials_build/"


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cached_ffmpeg(data_root: Path) -> Path:
    return data_root / "tools" / f"ffmpeg-{FFMPEG_VERSION}" / "ffmpeg.exe"


def locate_ffmpeg(data_root: Path) -> Path | None:
    cached = cached_ffmpeg(data_root)
    if cached.is_file() and _sha256(cached) == FFMPEG_EXE_SHA256:
        return cached
    system = shutil.which("ffmpeg")
    return Path(system).resolve() if system else None


def ensure_ffmpeg(
    data_root: Path,
    *,
    progress=None,
    archive_path: Path | None = None,
) -> Path:
    """Install a verified upstream FFmpeg executable into app data on demand."""
    if archive_path is None:
        existing = locate_ffmpeg(data_root)
        if existing:
            return existing
    target_dir = data_root / "tools" / f"ffmpeg-{FFMPEG_VERSION}"
    target_dir.mkdir(parents=True, exist_ok=True)
    cleanup_archive = archive_path is None
    if archive_path is None:
        fd, raw_path = tempfile.mkstemp(prefix="ffmpeg-", suffix=".zip", dir=target_dir)
        os.close(fd)
        archive_path = Path(raw_path)
        try:
            request = urllib.request.Request(FFMPEG_ARCHIVE_URL, headers={"User-Agent": "VideoDownloader/0.1"})
            with urllib.request.urlopen(request, timeout=45) as response, archive_path.open("wb") as output:
                total = int(response.headers.get("Content-Length") or 0)
                received = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    received += len(chunk)
                    if progress:
                        progress(received, total)
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise
    try:
        if _sha256(archive_path) != FFMPEG_ARCHIVE_SHA256:
            raise RuntimeError("FFmpeg 下载包校验失败，文件可能损坏或已被替换。")
        with zipfile.ZipFile(archive_path) as archive:
            wanted = {
                _PREFIX + "bin/ffmpeg.exe": "ffmpeg.exe",
                _PREFIX + "LICENSE": "LICENSE-FFmpeg-GPLv3.txt",
                _PREFIX + "README.txt": "README-FFmpeg-build.txt",
            }
            for member, filename in wanted.items():
                destination = target_dir / filename
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                with archive.open(member) as source, temporary.open("wb") as output:
                    shutil.copyfileobj(source, output)
                temporary.replace(destination)
        result = target_dir / "ffmpeg.exe"
        if _sha256(result) != FFMPEG_EXE_SHA256:
            result.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg 程序校验失败，已取消使用。")
        (target_dir / "SOURCE.txt").write_text(
            "Binary: " + FFMPEG_ARCHIVE_URL + "\n"
            "Corresponding FFmpeg source: " + FFMPEG_SOURCE_URL + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        if cleanup_archive:
            archive_path.unlink(missing_ok=True)
