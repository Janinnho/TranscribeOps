"""Authlib 1.9.5 still serves the web app's OIDC client and JOSE checks.

The app registers a Flask OAuth client, sends a nonce, and reads the email
from the ID token. 1.9.5 refuses an OpenSSH public key as an HMAC secret
(CVE-2026-114615) and still accepts an ordinary symmetric secret and an
RS256 ID token.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import authlib
from authlib.jose import JsonWebKey
from authlib.jose import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_ssh_public_key
from requests import Response

from app import create_app
from app import db
from app.models import SystemSetting
from app.models import User
from app.sso import get_oidc_client
from app.sso import oauth
from config import Config

ISSUER = "http://idp.test"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
TOKEN_URL = ISSUER + "/token"
CLIENT_ID = "transcribeops"
CLIENT_SECRET = "oidc-client-secret"


def _json_response(payload):
    response = Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode()
    response.headers["Content-Type"] = "application/json"
    response.url = ISSUER
    return response


def _rsa_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    ssh_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    jwk = JsonWebKey.import_key(public_pem, {"use": "sig", "alg": "RS256"}).as_dict()
    return private_pem, public_pem, ssh_public, jwk


def _id_token(private_pem, nonce, email="ada@example.com"):
    now = int(time.time())
    raw = jwt.encode(
        {"alg": "RS256"},
        {
            "iss": ISSUER,
            "sub": "user-1",
            "aud": CLIENT_ID,
            "exp": now + 600,
            "iat": now,
            "nonce": nonce,
            "email": email,
            "name": "Ada Lovelace",
        },
        private_pem,
    )
    return raw.decode() if isinstance(raw, bytes) else raw


class AuthlibOidcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.private_pem, self.public_pem, self.ssh_public, self.jwk = _rsa_material()
        self.metadata = {
            "issuer": ISSUER,
            "authorization_endpoint": ISSUER + "/authorize",
            "token_endpoint": TOKEN_URL,
            "userinfo_endpoint": ISSUER + "/userinfo",
            "jwks_uri": ISSUER + "/jwks",
            "jwks": {"keys": [self.jwk]},
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        self.token_body = {}

        class TestConfig(Config):
            SECRET_KEY = "test-secret"
            SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(self.tmp.name, "app.db")
            UPLOAD_FOLDER = os.path.join(self.tmp.name, "uploads")
            AUDIO_STORAGE_PATH = os.path.join(self.tmp.name, "audio")

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tmp.cleanup()

    def _http(self, method, url, **kwargs):
        if method == "GET" and url == DISCOVERY:
            return _json_response(self.metadata)
        if method == "POST" and url == TOKEN_URL:
            return _json_response(self.token_body)
        raise AssertionError(f"unexpected {method} {url}")

    def _enable_oidc(self, secret=CLIENT_SECRET):
        with self.app.app_context():
            rows = {
                "sso_enabled": "true",
                "sso_method": "oidc",
                "sso_auto_create": "true",
                "oidc_discovery_url": DISCOVERY,
                "oidc_client_id": CLIENT_ID,
                "oidc_scopes": "openid email profile",
            }
            if secret is not None:
                rows["oidc_client_secret"] = secret
            for key, value in rows.items():
                db.session.add(SystemSetting(key=key, value=value))
            db.session.commit()

    def test_installed_authlib_is_the_patched_release(self):
        self.assertEqual(authlib.__version__, "1.9.5")
        self.assertEqual(self.app.config["APP_VERSION"], "1.5.1")

    def test_sidebar_shows_the_release_version(self):
        self._enable_oidc()
        nonce_box = {}

        def http(session, method, url, **kwargs):
            if method == "POST" and url == TOKEN_URL and "id_token" not in self.token_body:
                query = parse_qs(urlparse(nonce_box["location"]).query)
                self.token_body.update({
                    "access_token": "access-token",
                    "token_type": "Bearer",
                    "id_token": _id_token(self.private_pem, query["nonce"][0]),
                })
            return self._http(method, url, **kwargs)

        with patch("requests.sessions.Session.request", http):
            start = self.client.get("/login")
            self.assertEqual(start.status_code, 302)
            nonce_box["location"] = start.headers["Location"]
            self.assertIn("nonce=", nonce_box["location"])
            query = parse_qs(urlparse(nonce_box["location"]).query)
            callback = self.client.get(
                "/oidc/callback?code=auth-code&state=" + query["state"][0],
                follow_redirects=True,
            )

        self.assertEqual(callback.status_code, 200)
        self.assertIn("v1.5.1", callback.get_data(as_text=True))
        with self.app.app_context():
            user = User.query.filter_by(email="ada@example.com").one()
            self.assertEqual(user.auth_source, "oidc")
            self.assertEqual(user.external_id, "user-1")
            self.assertEqual(user.display_name, "Ada Lovelace")

    def test_client_can_be_registered_again(self):
        self._enable_oidc()
        with self.app.app_context():
            first = get_oidc_client()
            second = get_oidc_client()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIn("oidc", oauth._registry)
        self.assertEqual(list(oauth._registry).count("oidc"), 1)

    def test_missing_client_secret_does_not_redirect(self):
        self._enable_oidc(secret=None)
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("idp.test", response.headers.get("Location", ""))

    def test_wrong_nonce_is_rejected(self):
        self._enable_oidc()
        self.token_body.update({
            "access_token": "access-token",
            "token_type": "Bearer",
            "id_token": _id_token(self.private_pem, "not-the-nonce"),
        })
        with patch("requests.sessions.Session.request", self._http):
            start = self.client.get("/login")
            query = parse_qs(urlparse(start.headers["Location"]).query)
            callback = self.client.get(
                "/oidc/callback?code=auth-code&state=" + query["state"][0]
            )
        self.assertEqual(callback.status_code, 200)
        self.assertIn("OIDC Token-Fehler", callback.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(email="ada@example.com").first())

    def test_ordinary_hmac_and_rsa_tokens_still_verify(self):
        secret = "hmac-secret-that-is-long-enough"
        signed = jwt.encode({"alg": "HS256"}, {"sub": "ada"}, secret)
        claims = jwt.decode(signed, secret)
        claims.validate()
        self.assertEqual(claims["sub"], "ada")

        raw = jwt.encode({"alg": "RS256"}, {"sub": "ada"}, self.private_pem)
        rsa_claims = jwt.decode(raw, self.public_pem)
        rsa_claims.validate()
        self.assertEqual(rsa_claims["sub"], "ada")

    def test_ssh_public_key_is_refused_as_hmac_secret(self):
        with self.assertRaises(ValueError):
            jwt.encode({"alg": "HS256"}, {"sub": "ada"}, self.ssh_public)

        # 1.9.5 completes CVE-2026-114615: a tab after the key type, and an
        # OpenSSH certificate, used to pass the prefix check.
        tabbed = self.ssh_public.replace(b" ", b"\t", 1)
        self.assertTrue(_loads_as_ssh(tabbed))
        with self.assertRaises(ValueError):
            jwt.encode({"alg": "HS256"}, {"sub": "ada"}, tabbed)

        certificate = _ssh_certificate()
        if certificate is None:
            return
        self.assertTrue(_loads_as_ssh(certificate))
        with self.assertRaises(ValueError):
            jwt.encode({"alg": "HS256"}, {"sub": "ada"}, certificate)


def _loads_as_ssh(raw_key):
    try:
        load_ssh_public_key(raw_key)
    except (ValueError, TypeError):
        return False
    return True


def _ssh_certificate():
    """Return an OpenSSH certificate line, or None when ssh-keygen is absent."""
    ssh_keygen = shutil.which("ssh-keygen")
    if not ssh_keygen:
        return None
    with tempfile.TemporaryDirectory() as directory:
        key_path = os.path.join(directory, "ca")
        subprocess.run(
            [ssh_keygen, "-q", "-t", "rsa", "-b", "2048", "-f", key_path, "-N", ""],
            check=True,
        )
        subprocess.run(
            [ssh_keygen, "-q", "-s", key_path, "-I", "testuser", "-n", "user", key_path + ".pub"],
            check=True,
        )
        with open(key_path + "-cert.pub", "rb") as handle:
            return handle.read().strip()


if __name__ == "__main__":
    unittest.main()
