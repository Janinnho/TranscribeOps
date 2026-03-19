"""SSO authentication helpers for TranscribeOps."""
from flask import request, redirect, url_for, session, current_app
from flask_login import login_user
from authlib.integrations.flask_client import OAuth
from app import db
from app.models import User, Group, SystemSetting

# Singleton OAuth instance, initialized lazily
oauth = OAuth()

# All SSO-related setting keys
SSO_KEYS = [
    'sso_enabled', 'sso_method',
    'sso_header_email', 'sso_header_name',
    'sso_auto_create', 'sso_default_admin',
    'oidc_discovery_url', 'oidc_client_id', 'oidc_client_secret',
    'oidc_scopes', 'oidc_email_claim', 'oidc_name_claim',
]


def get_sso_setting(key, default=''):
    """Read a single SSO-related SystemSetting."""
    setting = SystemSetting.query.get(key)
    return setting.value if setting else default


def is_sso_enabled():
    """Check whether SSO is activated."""
    return get_sso_setting('sso_enabled') == 'true'


def get_sso_method():
    """Return the active SSO method ('header' or 'oidc')."""
    return get_sso_setting('sso_method', 'header')


def get_all_sso_settings():
    """Return all SSO settings as a dict for the admin UI."""
    result = {}
    for k in SSO_KEYS:
        result[k] = get_sso_setting(k, '')
    return result


def save_sso_settings(form_data):
    """Persist SSO settings from admin form data."""
    for key in SSO_KEYS:
        value = form_data.get(key, '').strip()
        # For checkboxes submitted as 'on', convert to 'true'/'false'
        if key in ('sso_enabled', 'sso_auto_create', 'sso_default_admin'):
            value = 'true' if value in ('on', 'true') else 'false'
        # Don't overwrite oidc_client_secret with empty value
        if key == 'oidc_client_secret' and not value:
            continue
        setting = SystemSetting.query.get(key)
        if setting:
            setting.value = value
        else:
            db.session.add(SystemSetting(key=key, value=value))
    db.session.commit()


def _find_or_create_user(email, display_name, auth_source, external_id=None):
    """Find existing user by email or create a new one.

    Returns (user, created) tuple.
    """
    user = User.query.filter_by(email=email).first()
    if user:
        # Existing user found — do not overwrite auth_source
        return user, False

    if get_sso_setting('sso_auto_create') != 'true':
        return None, False

    # Create new SSO user
    user = User(
        display_name=display_name or email.split('@')[0],
        email=email,
        password_hash=None,
        is_admin=(get_sso_setting('sso_default_admin') == 'true'),
        auth_source=auth_source,
        external_id=external_id,
    )
    db.session.add(user)
    db.session.flush()

    # Auto-assign to default groups
    default_groups = Group.query.filter_by(is_default=True).all()
    for g in default_groups:
        user.groups.append(g)

    db.session.commit()
    return user, True


def try_header_sso_login():
    """Attempt to authenticate via trusted reverse-proxy headers.

    Returns (user, error_message) tuple.
    - (user, None) on success
    - (None, None) when no SSO header is present (not an error)
    - (None, 'message') on a specific error
    """
    header_email = get_sso_setting('sso_header_email')
    if not header_email:
        return None, 'SSO Header für E-Mail nicht konfiguriert.'

    email = request.headers.get(header_email, '').strip().lower()
    if not email:
        return None, None  # No header present — not an error

    header_name = get_sso_setting('sso_header_name')
    display_name = request.headers.get(header_name, '').strip() if header_name else ''

    user, created = _find_or_create_user(email, display_name, 'header_sso')
    if not user:
        return None, 'Benutzer nicht gefunden und automatische Erstellung ist deaktiviert.'
    if not user.is_active_user:
        return None, 'Ihr Konto ist deaktiviert.'

    return user, None


# --------------- OIDC helpers ---------------

def init_oidc(app):
    """Initialize the Authlib OAuth instance with the Flask app."""
    oauth.init_app(app)


def get_oidc_client():
    """Create/refresh the OIDC client from current SystemSetting values."""
    discovery_url = get_sso_setting('oidc_discovery_url')
    client_id = get_sso_setting('oidc_client_id')
    client_secret = get_sso_setting('oidc_client_secret')
    scopes = get_sso_setting('oidc_scopes', 'openid email profile')

    if not all([discovery_url, client_id, client_secret]):
        return None

    # Remove previously registered client to allow re-registration
    oauth._registry.pop('oidc', None)
    if hasattr(oauth, '_clients'):
        oauth._clients.pop('oidc', None)

    oauth.register(
        name='oidc',
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=discovery_url,
        client_kwargs={'scope': scopes},
    )
    return oauth.create_client('oidc')


def oidc_authorize_redirect(callback_url):
    """Start the OIDC authorization flow — returns a redirect response or None."""
    client = get_oidc_client()
    if not client:
        return None
    return client.authorize_redirect(callback_url)


def oidc_handle_callback():
    """Handle the OIDC callback and return (user, error_message)."""
    client = get_oidc_client()
    if not client:
        return None, 'OIDC nicht konfiguriert.'

    try:
        token = client.authorize_access_token()
    except Exception as e:
        return None, f'OIDC Token-Fehler: {str(e)}'

    userinfo = token.get('userinfo')
    if not userinfo:
        try:
            userinfo = client.userinfo()
        except Exception:
            return None, 'Benutzerinformationen konnten nicht abgerufen werden.'

    email_claim = get_sso_setting('oidc_email_claim', 'email')
    name_claim = get_sso_setting('oidc_name_claim', 'name')

    email = (userinfo.get(email_claim) or '').strip().lower()
    display_name = userinfo.get(name_claim, '')
    sub = userinfo.get('sub', '')

    if not email:
        return None, 'Keine E-Mail-Adresse im OIDC-Token gefunden.'

    user, created = _find_or_create_user(email, display_name, 'oidc', external_id=sub)
    if not user:
        return None, 'Benutzer nicht gefunden und automatische Erstellung ist deaktiviert.'
    if not user.is_active_user:
        return None, 'Ihr Konto ist deaktiviert.'

    return user, None
