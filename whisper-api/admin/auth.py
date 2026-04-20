"""Admin UI authentication (session + password)."""
import hmac
import time
from functools import wraps
from collections import defaultdict, deque

from flask import Blueprint, session, redirect, url_for, request, render_template, abort


_LOGIN_ATTEMPTS: dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
_RATE_WINDOW = 15 * 60  # 15 minutes
_MAX_ATTEMPTS = 5


def _rate_limited(ip: str) -> bool:
    now = time.time()
    q = _LOGIN_ATTEMPTS[ip]
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    return len(q) >= _MAX_ATTEMPTS


def _record_attempt(ip: str) -> None:
    _LOGIN_ATTEMPTS[ip].append(time.time())


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            if request.accept_mimetypes.best == "application/json" or request.path.startswith("/admin/api/"):
                return {"error": "auth required"}, 401
            return redirect(url_for("admin.login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def register_auth_routes(bp: Blueprint, config: dict) -> None:
    admin_password = config["admin_password"]

    @bp.before_request
    def _gate_admin():
        # If admin UI is not configured, return 503 for everything except /admin/disabled
        # and static assets (so the disabled page can still load CSS).
        if not admin_password:
            if request.endpoint in ("admin.disabled", "admin.static"):
                return None
            return render_template("disabled.html"), 503

    @bp.route("/disabled")
    def disabled():
        return render_template("disabled.html"), 503

    @bp.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("admin"):
            return redirect(url_for("admin.dashboard"))
        error = None
        if request.method == "POST":
            ip = request.remote_addr or "unknown"
            if _rate_limited(ip):
                error = "Zu viele Fehlversuche. Bitte später erneut versuchen."
            else:
                submitted = request.form.get("password", "")
                if admin_password and hmac.compare_digest(submitted, admin_password):
                    session["admin"] = True
                    session.permanent = True
                    nxt = request.args.get("next") or url_for("admin.dashboard")
                    return redirect(nxt)
                _record_attempt(ip)
                error = "Falsches Passwort."
        return render_template("login.html", error=error)

    @bp.route("/logout", methods=["POST", "GET"])
    def logout():
        session.pop("admin", None)
        return redirect(url_for("admin.login"))
