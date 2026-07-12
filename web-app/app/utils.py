from urllib.parse import urlparse
from zoneinfo import ZoneInfo


def safe_next_url(nxt):
    """Return `nxt` only if it's a safe relative path on this host.

    Blocks open redirects: rejects absolute URLs (scheme/netloc), protocol-
    relative URLs (`//evil.com`) and backslash variants (`/\\evil.com`) that
    browsers normalize to slashes.
    """
    if not nxt or not isinstance(nxt, str):
        return None
    if '\\' in nxt or not nxt.startswith('/') or nxt.startswith('//'):
        return None
    parsed = urlparse(nxt)
    if parsed.scheme or parsed.netloc:
        return None
    return nxt


def get_system_timezone():
    """Return the configured system timezone string (e.g. 'Europe/Berlin')."""
    from app.models import SystemSetting
    setting = SystemSetting.query.get('timezone')
    return setting.value if setting else 'Europe/Berlin'


def format_dt(dt):
    """Convert a UTC datetime to the system timezone and format as 'DD.MM.YYYY HH:MM'."""
    if dt is None:
        return ''
    tz = ZoneInfo(get_system_timezone())
    return dt.replace(tzinfo=ZoneInfo('UTC')).astimezone(tz).strftime('%d.%m.%Y %H:%M')


def now_local():
    """Return current datetime in the system timezone."""
    from datetime import datetime, timezone
    tz = ZoneInfo(get_system_timezone())
    return datetime.now(timezone.utc).astimezone(tz)
