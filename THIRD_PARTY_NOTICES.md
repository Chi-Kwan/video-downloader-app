# Third-party notices

The Windows executable contains third-party Python packages and runtime files.
Their original license texts are preserved under `licenses/`. The generated
component inventory is available in `third-party-components.json`, and hashes
of native files found in the executable audit are listed in
`native-components.json`.

Important bundled components include:

- yt-dlp (Unlicense)
- pywebview (BSD-3-Clause)
- Python and the Python standard library (PSF License)
- PyInstaller bootloader and build-time modules (GPL-2.0-or-later with the
  PyInstaller bootloader exception)
- pythonnet and clr-loader (MIT)
- Microsoft.Web.WebView2 SDK loader files (Microsoft license and notices)
- certifi (MPL-2.0); the corresponding installed source snapshot is preserved
  in `third_party_sources/`

The inventories are provided to make the release auditable; the license file
for each dependency is authoritative if a short identifier differs from
package metadata.

## FFmpeg is not bundled

FFmpeg is not embedded in the repository or release executable. When merging
separate high-quality video and audio streams is required, the application
first looks for a system installation. If none is available, it downloads the
following fixed upstream build directly to the user's application-data folder:

- Binary archive: https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip
- Archive SHA-256: `fa7d4d7e795db0e2503f49f105f46ed5852386f0cfdd819899be3b65ebde24fc`
- Extracted `ffmpeg.exe` SHA-256: `2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3`
- Corresponding FFmpeg source: https://github.com/FFmpeg/FFmpeg/commit/b08d7969c5

The downloaded archive identifies that build as GPLv3. Its `LICENSE` and
`README.txt` are extracted next to the downloaded executable, together with a
`SOURCE.txt` file containing the binary and source URLs. FFmpeg remains a
separate program invoked by the downloader; it is not relicensed under this
project's MIT License.
