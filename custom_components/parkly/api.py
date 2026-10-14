"""Minimal async client for Parkly (api.parkly.no).

Login is Parkly's Azure AD B2C policy, done with plain HTTP (no browser):
  GET  {B2C}/oauth2/v2.0/authorize (PKCE)       -> login page with csrf + transId
  POST {B2C}/SelfAsserted (signInName, password) -> {"status": "200"}
  GET  {B2C}/api/CombinedSigninAndSignup/confirmed -> 302 to app.parkly.no?code=...
  POST {B2C}/oauth2/v2.0/token                  -> access (1 h) + refresh (24 h) token
Data:
  GET  https://api.parkly.no/api/prepaidpackage/assignments
       -> {"prepaidServicePermits": [{id, serviceName, totalServiceSpaceCount,
           activeServiceSpaceCount, activeLicensePlatesForAssignment, parkingLotName,
           areas, companyName, ...}]}
       activeLicensePlatesForAssignment holds the account's own plates parked in that zone now.
  GET  https://api.parkly.no/api/user/activity
       -> [{startTime, endTime, parkingLotAreaName, serviceName, licensePlateNumber, ...}]
          finished parking segments only (one per area visited); ~300 KB
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

CLIENT_ID = "68841595-6caf-4778-b02b-1ec681884288"
REDIRECT_URI = "https://app.parkly.no"
SCOPE = "https://b2cparklyidpprd.onmicrosoft.com/customer-api/read openid profile offline_access"
POLICY = "B2C_1A_signup_signin"
B2C = f"https://login.parkly.no/login.parkly.no/{POLICY}"
API_URL = "https://api.parkly.no/"
USER_AGENT = "Mozilla/5.0 (Home Assistant; ha-parkly)"
TIMEOUT = aiohttp.ClientTimeout(total=30)


class ParklyError(Exception):
    """Base error."""


class ParklyAuthError(ParklyError):
    """Wrong e-mail or password."""


class ParklyConnectionError(ParklyError):
    """Network or server problem."""


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


class ParklyApi:
    """Talks to Parkly for one account. Keeps tokens in memory only."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._access: str | None = None
        self._refresh: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    # -- auth --------------------------------------------------------------

    async def login(self) -> None:
        """Full e-mail/password login against the B2C pages (separate session, no shared cookies)."""
        verifier, challenge = _pkce()
        params = {
            "client_id": CLIENT_ID, "response_type": "code", "redirect_uri": REDIRECT_URI,
            "response_mode": "query", "scope": SCOPE, "code_challenge_method": "S256",
            "code_challenge": challenge, "ui_locales": "nb",
        }
        # B2C sets a cookie whose name contains "|", which aiohttp's cookie jar mangles,
        # so cookies are carried by hand.
        cookies: dict[str, str] = {}

        def remember(resp: aiohttp.ClientResponse) -> None:
            for raw in resp.headers.getall("Set-Cookie", []):
                name, _, value = raw.split(";", 1)[0].partition("=")
                cookies[name.strip()] = value.strip()

        def headers(**extra: str) -> dict[str, str]:
            return {"User-Agent": USER_AGENT, "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()), **extra}

        try:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar(), timeout=TIMEOUT) as web:
                async with web.get(f"{B2C}/oauth2/v2.0/authorize", params=params, headers=headers()) as r:
                    remember(r)
                    page = await r.text()
                csrf = re.search(r'"csrf":"([^"]+)"', page)
                trans = re.search(r'"transId":"([^"]+)"', page)
                if not csrf or not trans:
                    raise ParklyConnectionError("Login page changed (no csrf/transId)")
                csrf, trans = csrf.group(1), trans.group(1)

                async with web.post(
                    f"{B2C}/SelfAsserted", params={"tx": trans, "p": POLICY},
                    data={"request_type": "RESPONSE", "signInName": self._email, "password": self._password},
                    headers=headers(**{"X-CSRF-TOKEN": csrf, "X-Requested-With": "XMLHttpRequest"}),
                ) as r:
                    remember(r)
                    if r.status != 200:
                        raise ParklyConnectionError(f"Login step failed: HTTP {r.status}")
                    result = await r.json(content_type=None)
                if str(result.get("status")) != "200":
                    raise ParklyAuthError(result.get("message") or "Login rejected")

                async with web.get(
                    f"{B2C}/api/CombinedSigninAndSignup/confirmed",
                    params={"rememberMe": "false", "csrf_token": csrf, "tx": trans, "p": POLICY},
                    headers=headers(), allow_redirects=False,
                ) as r:
                    location = r.headers.get("Location", "")
                code = parse_qs(urlparse(location).query).get("code", [None])[0]
                if not code:
                    raise ParklyAuthError("No authorization code after login")
        except aiohttp.ClientError as err:
            raise ParklyConnectionError(str(err)) from err

        await self._token({
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT_URI, "code_verifier": verifier,
        })

    async def _token(self, form: dict[str, str]) -> None:
        data = {"client_id": CLIENT_ID, "scope": SCOPE, **form}
        try:
            async with self._session.post(f"{B2C}/oauth2/v2.0/token", data=data, timeout=TIMEOUT) as r:
                body = await r.json(content_type=None)
                status = r.status
        except aiohttp.ClientError as err:
            raise ParklyConnectionError(str(err)) from err
        if status != 200 or "access_token" not in body:
            raise ParklyAuthError(body.get("error_description") or body.get("error") or f"HTTP {status}")
        self._access = body["access_token"]
        self._refresh = body.get("refresh_token") or self._refresh
        self._expires = time.monotonic() + int(body.get("expires_in", 3600))

    async def _ensure_token(self) -> None:
        async with self._lock:
            if self._access and time.monotonic() < self._expires - 300:
                return
            if self._refresh:
                try:
                    await self._token({"grant_type": "refresh_token", "refresh_token": self._refresh})
                    return
                except ParklyAuthError:
                    _LOGGER.debug("Refresh token rejected, logging in again")
                    self._refresh = None
            await self.login()

    # -- data --------------------------------------------------------------

    async def _get(self, path: str, retry: bool = True) -> Any:
        await self._ensure_token()
        try:
            async with self._session.get(
                API_URL + path, timeout=TIMEOUT,
                headers={"Authorization": f"Bearer {self._access}", "Accept": "application/json",
                         "User-Agent": USER_AGENT},
            ) as r:
                if r.status == 401 and retry:
                    self._access = None
                    return await self._get(path, retry=False)
                if r.status != 200:
                    raise ParklyConnectionError(f"{path}: HTTP {r.status}")
                return await r.json(content_type=None)
        except aiohttp.ClientError as err:
            raise ParklyConnectionError(str(err)) from err

    async def get_permits(self) -> list[dict[str, Any]]:
        """Agreement parking permits (one per zone), sorted by id."""
        data = await self._get("api/prepaidpackage/assignments")
        permits = (data or {}).get("prepaidServicePermits") or []
        return sorted(permits, key=lambda p: p.get("id", 0))

    async def get_activity(self) -> list[dict[str, Any]]:
        """Finished parking segments, newest first."""
        data = await self._get("api/user/activity")
        items = data if isinstance(data, list) else []
        return sorted(items, key=lambda a: a.get("startTime") or "", reverse=True)
