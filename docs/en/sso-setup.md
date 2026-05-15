# Single Sign-On (SSO) Setup Guide

TranscribeOps supports two SSO methods for enterprise authentication:

1. **Header-based SSO** — for reverse proxies that inject authenticated user information as HTTP headers (e.g., Cloudflare Access, Entra ID Application Proxy, Authentik, oauth2-proxy)
2. **OpenID Connect (OIDC)** — for direct integration with identity providers (e.g., Microsoft Entra ID, Keycloak, Google Workspace, Okta)

---

## Table of Contents

- [Overview](#overview)
- [Admin Configuration](#admin-configuration)
- [Header-based SSO](#header-based-sso)
  - [Cloudflare Access](#cloudflare-access)
  - [nginx + oauth2-proxy](#nginx--oauth2-proxy)
  - [Authentik](#authentik)
- [OpenID Connect (OIDC)](#openid-connect-oidc)
  - [Microsoft Entra ID](#microsoft-entra-id)
  - [Keycloak](#keycloak)
  - [Google Workspace](#google-workspace)
- [General Settings](#general-settings)
- [Security Considerations](#security-considerations)
- [Manual Login Fallback](#manual-login-fallback)
- [Troubleshooting](#troubleshooting)

---

## Overview

When SSO is enabled:

- Visiting the application automatically triggers the SSO login flow
- Users are matched by their email address — if a user with that email already exists, they are logged in as that user
- New users can optionally be auto-created on first SSO login
- Manual login with local credentials is always available at `/manuell-login`
- After logout, a "Login" button is shown that re-triggers the SSO flow

### User Matching

SSO users are identified by their **email address**. When an SSO login occurs:

1. TranscribeOps searches for an existing user with that email
2. If found, the user is logged in (regardless of whether the account was created locally or via SSO)
3. If not found and **auto-create** is enabled, a new user is created with the SSO email and display name
4. If not found and auto-create is disabled, login fails with an error message

---

## Admin Configuration

All SSO settings are managed in the **Admin Portal** under the **Single-Sign-On** tab.

### Steps

1. Log in as an admin user
2. Navigate to **Admin** in the sidebar
3. Click the **Single-Sign-On** tab
4. Enable SSO and choose your method (Header-based or OIDC)
5. Fill in the configuration fields
6. Optionally enable auto-creation of new users
7. Click **Save SSO settings**

---

## Header-based SSO

Header-based SSO relies on a reverse proxy that authenticates users and passes their identity as HTTP headers to TranscribeOps.

### How it works

```
User -> Reverse Proxy (authenticates) -> TranscribeOps
                                          reads headers:
                                          - email header -> user identity
                                          - name header -> display name (optional)
```

### Configuration Fields

| Field | Description | Example |
|-------|-------------|---------|
| **Email header** | HTTP header containing the authenticated user's email | `Cf-Access-Authenticated-User-Email` |
| **Name header** | HTTP header containing the display name (optional) | `X-Auth-Name` |

---

### Cloudflare Access

[Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/applications/) authenticates users and forwards their identity via HTTP headers.

#### Setup Steps

1. **Create an Access Application** in the Cloudflare Zero Trust dashboard
   - Go to **Access > Applications > Add an application**
   - Choose **Self-hosted**
   - Set the application domain to your TranscribeOps URL
   - Configure an Access Policy (e.g., allow specific email domains)

2. **Configure TranscribeOps SSO settings**
   - SSO method: **Header-based**
   - Email header: `Cf-Access-Authenticated-User-Email`
   - Name header: *(leave empty — Cloudflare Access does not send a name header by default)*

3. **Ensure direct access is blocked**
   - TranscribeOps must only be accessible through Cloudflare's proxy
   - Configure firewall rules to block direct access to the server

#### Cloudflare Headers Reference

| Header | Content |
|--------|---------|
| `Cf-Access-Authenticated-User-Email` | Authenticated user's email address |
| `Cf-Access-Jwt-Assertion` | JWT token (not used by TranscribeOps) |

---

### nginx + oauth2-proxy

[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) is a reverse proxy that provides authentication via various OAuth2 providers.

#### Setup Steps

1. **Deploy oauth2-proxy** alongside TranscribeOps
   - Configure oauth2-proxy with your OAuth2 provider (Google, GitHub, etc.)
   - Set `--pass-user-headers=true` to forward user information as headers

2. **nginx configuration** (example):

```nginx
server {
    listen 443 ssl;
    server_name transcribeops.example.com;

    location /oauth2/ {
        proxy_pass http://oauth2-proxy:4180;
    }

    location / {
        auth_request /oauth2/auth;
        auth_request_set $email $upstream_http_x_auth_request_email;
        auth_request_set $name  $upstream_http_x_auth_request_preferred_username;

        proxy_set_header X-Auth-Email $email;
        proxy_set_header X-Auth-Name  $name;
        proxy_pass http://transcribeops:5000;
    }
}
```

3. **Configure TranscribeOps SSO settings**
   - SSO method: **Header-based**
   - Email header: `X-Auth-Email`
   - Name header: `X-Auth-Name`

---

### Authentik

[Authentik](https://goauthentik.io/) is an open-source identity provider that supports proxy authentication.

#### Setup Steps

1. **Create a Proxy Provider** in Authentik
   - Go to **Applications > Providers > Create > Proxy Provider**
   - Set the external URL to your TranscribeOps domain
   - Set the internal URL to `http://transcribeops:5000`

2. **Configure TranscribeOps SSO settings**
   - SSO method: **Header-based**
   - Email header: `X-authentik-email`
   - Name header: `X-authentik-name`

---

## OpenID Connect (OIDC)

OIDC integrates directly with identity providers without requiring a reverse proxy for authentication.

### How it works

```
User -> TranscribeOps /login
     -> Redirect to OIDC Provider
     -> User authenticates at Provider
     -> Redirect back to /oidc/callback
     -> Token exchange + user info
     -> User logged in
```

### Configuration Fields

| Field | Description | Example |
|-------|-------------|---------|
| **Discovery URL** | OIDC Discovery endpoint (`.well-known/openid-configuration`) | `https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration` |
| **Client ID** | Application/Client ID from the identity provider | `a1b2c3d4-...` |
| **Client Secret** | Application secret | *(stored securely, not displayed after saving)* |
| **Scopes** | OAuth2 scopes to request | `openid email profile` |
| **Email claim** | JWT claim containing the email address | `email` |
| **Name claim** | JWT claim containing the display name | `name` |

### Callback URL

The OIDC callback URL that must be registered with your identity provider is:

```
https://your-transcribeops-domain.com/oidc/callback
```

> **Important**: The callback URL must use HTTPS in production and match exactly what is configured in the identity provider.

---

### Microsoft Entra ID

#### Setup Steps

1. **Register an Application** in Azure Portal
   - Go to **Microsoft Entra ID > App registrations > New registration**
   - Name: `TranscribeOps`
   - Redirect URI: `https://your-domain.com/oidc/callback` (Web)

2. **Create a Client Secret**
   - Go to **Certificates & secrets > New client secret**
   - Copy the secret value (shown only once)

3. **Configure API Permissions**
   - Add **Microsoft Graph > Delegated > openid, email, profile**
   - Grant admin consent

4. **Find your Discovery URL**
   ```
   https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration
   ```
   Replace `{tenant-id}` with your Azure AD tenant ID.

5. **Configure TranscribeOps SSO settings**
   - SSO method: **OpenID Connect (OIDC)**
   - Discovery URL: `https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration`
   - Client ID: *(from step 1)*
   - Client Secret: *(from step 2)*
   - Scopes: `openid email profile`
   - Email claim: `email`
   - Name claim: `name`

---

### Keycloak

#### Setup Steps

1. **Create a Client** in Keycloak
   - Go to **Clients > Create client**
   - Client ID: `transcribeops`
   - Client Protocol: `openid-connect`
   - Root URL: `https://your-domain.com`
   - Valid Redirect URIs: `https://your-domain.com/oidc/callback`
   - Access Type: `confidential`

2. **Get Client Secret**
   - Go to **Clients > transcribeops > Credentials**
   - Copy the secret

3. **Find your Discovery URL**
   ```
   https://keycloak.example.com/realms/{realm}/.well-known/openid-configuration
   ```

4. **Configure TranscribeOps SSO settings**
   - Discovery URL: `https://keycloak.example.com/realms/{realm}/.well-known/openid-configuration`
   - Client ID: `transcribeops`
   - Client Secret: *(from step 2)*
   - Scopes: `openid email profile`
   - Email claim: `email`
   - Name claim: `name`

---

### Google Workspace

#### Setup Steps

1. **Create OAuth2 Credentials** in Google Cloud Console
   - Go to **APIs & Services > Credentials > Create Credentials > OAuth 2.0 Client IDs**
   - Application type: **Web application**
   - Authorized redirect URIs: `https://your-domain.com/oidc/callback`

2. **Configure TranscribeOps SSO settings**
   - Discovery URL: `https://accounts.google.com/.well-known/openid-configuration`
   - Client ID: *(from step 1)*
   - Client Secret: *(from step 1)*
   - Scopes: `openid email profile`
   - Email claim: `email`
   - Name claim: `name`

---

## General Settings

### Auto-Create Users

When enabled, users who authenticate via SSO for the first time will have an account automatically created for them. The new account will:

- Use the email address from the SSO provider
- Use the display name from the SSO provider (or the email prefix if not available)
- Be assigned to all default groups
- Be active immediately

When disabled, only pre-existing users (created by an admin) can log in via SSO. This is useful when you want to control exactly who has access.

### Default Admin

When enabled, auto-created SSO users will be given admin privileges. **This should only be enabled during initial setup** and disabled afterwards.

---

## Security Considerations

### Header-based SSO

> **Critical**: Header-based SSO trusts HTTP headers to identify users. If the application is accessible directly (bypassing the reverse proxy), an attacker can forge these headers and impersonate any user.

**Required safeguards:**

- TranscribeOps must **only** be accessible through the reverse proxy
- Block direct access via firewall rules, Docker network isolation, or bind the application to `127.0.0.1`
- Never expose the application port directly to the internet

### OIDC

- The **Client Secret** is stored in the database. Ensure database access is restricted.
- Use **HTTPS** for the callback URL in production — OIDC providers typically require it
- The Flask `SECRET_KEY` must be set to a strong random value (used for session security during the OIDC flow)
- Set `SESSION_COOKIE_SAMESITE='Lax'` if you experience issues with OIDC redirects

### General

- SSO users who are created with `password_hash=None` cannot log in via the manual login form
- The admin can deactivate SSO users by setting them to inactive in the user management
- All SSO-created users are visible in the admin user table with their authentication source (Header SSO / OIDC / Local)

---

## Manual Login Fallback

Manual login with local credentials is **always** available at:

```
https://your-domain.com/manuell-login
```

This is useful for:

- Initial admin setup before SSO is configured
- Emergency access if the SSO provider is down
- Local service accounts that should not use SSO

> **Tip**: Bookmark the manual login URL before enabling SSO to ensure you always have access.

---

## Troubleshooting

### Header-based SSO: "User not found and automatic creation is disabled"

The SSO header contains an email that doesn't match any existing user, and auto-create is disabled. Either:
- Create the user manually in the admin portal first
- Enable "Create users automatically" in the SSO settings

### Header-based SSO: Login page shows instead of auto-login

The expected header is not present in the request. This usually means:
- The user is accessing the app directly instead of through the reverse proxy
- The header name in the SSO configuration doesn't match what the proxy sends
- Check the exact header name (case-sensitive) in the proxy configuration

### OIDC: "OIDC is not fully configured"

One or more required OIDC fields are empty:
- Discovery URL
- Client ID
- Client Secret

### OIDC: "OIDC token error"

The token exchange failed. Common causes:
- Client Secret is incorrect
- Callback URL doesn't match the one registered with the identity provider
- Clock skew between TranscribeOps server and OIDC provider

### OIDC: "No email address found in the OIDC token"

The identity provider didn't include an email in the token. Check:
- The `email` scope is included in the Scopes setting
- The Email claim setting matches the actual claim name in the provider's tokens
- The user has an email configured in the identity provider

### OIDC: Redirect URL mismatch

Ensure the callback URL registered with your identity provider exactly matches:
```
https://your-domain.com/oidc/callback
```

If TranscribeOps is behind a reverse proxy, you may need to configure `PREFERRED_URL_SCHEME=https` and set the proxy headers correctly so Flask generates the correct external URL.

### General: Locked out after enabling SSO

Use the manual login at `/manuell-login` with your local admin credentials to access the admin portal and adjust the SSO settings.
