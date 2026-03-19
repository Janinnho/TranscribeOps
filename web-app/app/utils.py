from zoneinfo import ZoneInfo


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
