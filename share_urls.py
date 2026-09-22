"""Resolve public Xiaohongshu shares without following the login-page detour."""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urljoin, urlsplit


SHORT_HOSTS = {'xhslink.cn', 'www.xhslink.cn', 'xhslink.com', 'www.xhslink.com'}
NOTE_HOSTS = {'xiaohongshu.com', 'www.xiaohongshu.com'}
NOTE_PATH = re.compile(r'^/(?:explore|discovery/item)/([0-9a-f]{24})/?$', re.I)


def is_xhs_short(url: str) -> bool:
    return (urlsplit(url).hostname or '').lower() in SHORT_HOSTS


def normalize_xhs_url(url: str) -> str:
    """Unwrap once per login wrapper; never unquote the nested token a second time."""
    current = url
    for _ in range(5):
        parts = urlsplit(current)
        host = (parts.hostname or '').lower()
        if host not in NOTE_HOSTS:
            return current
        if parts.path.rstrip('/') != '/login':
            if NOTE_PATH.fullmatch(parts.path):
                return parts._replace(scheme='https', netloc='www.xiaohongshu.com', fragment='').geturl()
            return current
        nested = parse_qs(parts.query).get('redirectPath', [''])[0]
        if not nested:
            raise ValueError('这是小红书登录页，没有笔记地址。请粘贴手机分享链接或笔记链接。')
        candidate = urljoin('https://www.xiaohongshu.com/', nested)
        target = urlsplit(candidate)
        if (target.scheme not in ('http', 'https') or target.hostname not in NOTE_HOSTS
                or target.username or target.password or target.port not in (None, 80, 443)):
            raise ValueError('小红书跳转参数不是有效的本站笔记地址。')
        if candidate == current:
            break
        current = candidate
    raise ValueError('小红书链接包含过多或循环跳转，请重新复制原始分享链接。')


class _StopRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_xhs_share(url: str, *, direct: bool = False, check_cancel=None, opener=None) -> str:
    current = normalize_xhs_url(url)
    if not is_xhs_short(current):
        return current
    if opener is None:
        handlers = [_StopRedirect()]
        if direct:
            handlers.append(urllib.request.ProxyHandler({}))
        opener = urllib.request.build_opener(*handlers)
    visited = set()
    for _ in range(6):
        if check_cancel:
            check_cancel()
        current = normalize_xhs_url(current)
        parts = urlsplit(current)
        if parts.hostname in NOTE_HOSTS and NOTE_PATH.fullmatch(parts.path):
            return current
        if parts.hostname not in SHORT_HOSTS or parts.scheme not in ('http', 'https'):
            raise ValueError('小红书短链接没有跳转到受支持的笔记页面。')
        if parts.username or parts.password or parts.port not in (None, 80, 443):
            raise ValueError('小红书短链接格式不正确。')
        if current in visited:
            raise ValueError('小红书短链接发生循环跳转，请重新复制分享链接。')
        visited.add(current)
        request = urllib.request.Request(current, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            response = opener.open(request, timeout=15)
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise
            response = exc
        with response:
            location = response.headers.get('Location')
            if not location:
                raise ValueError('未能解析小红书分享链接，链接可能已失效。请复制笔记页面的完整地址。')
            current = urljoin(current, location)
    raise ValueError('小红书短链接跳转次数过多，请重新复制分享链接。')
