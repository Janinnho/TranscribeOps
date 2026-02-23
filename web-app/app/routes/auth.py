from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User
from app.sso import (
    is_sso_enabled, get_sso_method,
    try_header_sso_login, oidc_authorize_redirect, oidc_handle_callback,
)

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Main login endpoint. Behavior depends on SSO configuration."""
    if current_user.is_authenticated:
        return redirect(url_for('main.transcription'))

    if not is_sso_enabled():
        # Classic email/password login
        return _handle_local_login()

    method = get_sso_method()

    if method == 'header':
        # Try header-based SSO
        user, error = try_header_sso_login()
        if user:
            login_user(user, remember=True)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.transcription'))
        if error:
            flash(error, 'danger')
        # If no header present (error is None), show SSO login page with button
        return render_template('auth/sso_login.html', sso_method='header', error=error)

    elif method == 'oidc':
        # Redirect to OIDC provider
        callback_url = url_for('auth.oidc_callback', _external=True)
        response = oidc_authorize_redirect(callback_url)
        if response is None:
            flash('OIDC ist nicht vollständig konfiguriert.', 'danger')
            return render_template('auth/sso_login.html', sso_method='oidc', error=True)
        return response

    return _handle_local_login()


@auth_bp.route('/oidc/callback')
def oidc_callback():
    """Handle OIDC provider callback."""
    user, error = oidc_handle_callback()
    if error:
        flash(error, 'danger')
        return render_template('auth/sso_login.html', sso_method='oidc', error=error)
    if user:
        login_user(user, remember=True)
        return redirect(url_for('main.transcription'))
    flash('Anmeldung fehlgeschlagen.', 'danger')
    return redirect(url_for('auth.login'))


@auth_bp.route('/manuell-login', methods=['GET', 'POST'])
def manual_login():
    """Manual login with local email/password — always available."""
    if current_user.is_authenticated:
        return redirect(url_for('main.transcription'))
    return _handle_local_login(template='auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    if is_sso_enabled():
        return render_template('auth/sso_logout.html')
    return redirect(url_for('auth.login'))


def _handle_local_login(template='auth/login.html'):
    """Process classic email/password login form."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_active_user:
            login_user(user, remember=True)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.transcription'))
        flash('Ungültige E-Mail-Adresse oder Passwort.', 'danger')
    return render_template(template)
