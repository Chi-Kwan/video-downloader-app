"""Read the active public Douyin player, never recommendation/preload requests."""
from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs


PLAYER_SNAPSHOT = r"""(() => {
  const videos = [...document.querySelectorAll('video')].map(v => {
    const r = v.getBoundingClientRect();
    const s = getComputedStyle(v);
    const visible = Math.max(0, Math.min(r.right, innerWidth)-Math.max(r.left, 0)) *
                    Math.max(0, Math.min(r.bottom, innerHeight)-Math.max(r.top, 0));
    return {v, visible: s.display === 'none' || s.visibility === 'hidden' ? 0 : visible};
  }).filter(x => x.visible > 10000).sort((a,b) => b.visible-a.visible);
  const v = videos[0]?.v;
  return {page_url: location.href, title: document.title, user_agent: navigator.userAgent,
    media_url: v?.currentSrc || v?.src || '', ready: v?.readyState || 0,
    width: v?.videoWidth || 0, height: v?.videoHeight || 0,
    duration: Number.isFinite(v?.duration) ? v.duration : 0,
    encrypted: !!v?.mediaKeys};
})()"""


def video_id(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if host != 'douyin.com' and not host.endswith('.douyin.com'):
        return ''
    match = re.search(r'/video/(\d{8,})', parsed.path)
    if match:
        return match.group(1)
    value = parse_qs(parsed.query).get('modal_id', [''])[0]
    return value if re.fullmatch(r'\d{8,}', value) else ''


def validate_snapshot(snapshot: dict, expected_id: str = '') -> dict:
    actual = video_id(str(snapshot.get('page_url', '')))
    if not actual or (expected_id and actual != expected_id):
        raise ValueError('请保持在原链接的视频页面，不能切换到其他视频。')
    if snapshot.get('encrypted'):
        raise ValueError('该视频使用受保护的播放器，不能通过此功能下载。')
    media_url = str(snapshot.get('media_url', ''))
    parsed = urlparse(media_url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in ('http', 'https') or not any(
        host == d or host.endswith('.' + d)
        for d in ('douyinvod.com', 'douyin.com', 'bytecdn.cn', 'bytecdn.com', 'ibytedtos.com')
    ):
        raise ValueError('尚未识别到当前视频的可下载地址，请播放原视频后重试。')
    if not snapshot.get('width') or not snapshot.get('duration') or snapshot.get('ready', 0) < 2:
        raise ValueError('视频尚未加载完成，请等待画面播放后重试。')
    return dict(snapshot, id=actual)


def media_info(snapshot: dict) -> dict:
    media = validate_snapshot(snapshot, str(snapshot.get('id', '')))
    return {
        'id': media['id'], 'title': media.get('title') or media['id'],
        'url': media['media_url'], 'ext': 'mp4',
        'width': media['width'], 'height': media['height'],
        'duration': media['duration'],
        'http_headers': {'Referer': media['page_url'], 'User-Agent': media['user_agent']},
    }
