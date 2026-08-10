"""
Thin client for the Hootsuite REST API (https://platform.hootsuite.com).

Covers only what the calendar build needs: OAuth token refresh, social profile
lookup, outbound message retrieval, and media download-URL resolution.

API reference: https://platform.hootsuite.com/docs/api/swagger.yaml
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import requests

BASE = "https://platform.hootsuite.com"
TOKEN_URL = f"{BASE}/oauth2/token"
AUTH_URL = f"{BASE}/oauth2/auth"

# GET /v1/messages rejects any window wider than 4 weeks (error 40020).
# 7 days keeps each request comfortably under the row limit for TRPL's volume
# (roughly six messages a day), so the bisecting fallback rarely has to fire.
MAX_WINDOW_DAYS = 7
MIN_WINDOW_DAYS = 1

# The API caps a page at 100 (error otherwise).
PAGE_LIMIT = 100

# Documented ceiling is 20 req/sec. We stay far below it; this is just politeness
# so a large media backlog does not burst.
MIN_SECONDS_BETWEEN_CALLS = 0.06


class HootsuiteError(RuntimeError):
    pass


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    expires_in: int


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> TokenSet:
    """Exchange a refresh token for a new access token.

    Hootsuite refresh tokens are SINGLE USE. The response contains a brand new
    refresh_token which must be persisted immediately; the one passed in is dead
    the moment this call succeeds.
    """
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": _basic_auth_header(client_id, client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=30,
    )
    if resp.status_code != 200:
        raise HootsuiteError(
            f"Token refresh failed ({resp.status_code}). "
            f"The stored refresh token is probably spent or revoked - re-run "
            f"scripts/bootstrap_auth.py to mint a new one. Body: {resp.text[:400]}"
        )
    payload = resp.json()
    new_refresh = payload.get("refresh_token")
    if not new_refresh:
        raise HootsuiteError(
            "Token response contained no refresh_token. The app was probably "
            "authorized without the 'offline' scope; re-run bootstrap_auth.py."
        )
    return TokenSet(
        access_token=payload["access_token"],
        refresh_token=new_refresh,
        expires_in=int(payload.get("expires_in", 3600)),
    )


def exchange_authorization_code(
    client_id: str, client_secret: str, code: str, redirect_uri: str
) -> TokenSet:
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": _basic_auth_header(client_id, client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise HootsuiteError(
            f"Code exchange failed ({resp.status_code}): {resp.text[:400]}"
        )
    payload = resp.json()
    if "refresh_token" not in payload:
        raise HootsuiteError(
            "No refresh_token returned. Make sure the authorize URL requested "
            "scope=offline."
        )
    return TokenSet(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_in=int(payload.get("expires_in", 3600)),
    )


class Hootsuite:
    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
        )
        self._last_call = 0.0

    # ----- plumbing ---------------------------------------------------------

    def _get(self, path: str, params: Any = None) -> dict:
        delay = self._last_call + MIN_SECONDS_BETWEEN_CALLS - time.monotonic()
        if delay > 0:
            time.sleep(delay)

        for attempt in range(5):
            resp = self.session.get(f"{BASE}{path}", params=params, timeout=45)
            self._last_call = time.monotonic()

            if resp.status_code == 429:
                back_off = 2 ** attempt
                print(f"  rate limited on {path}, sleeping {back_off}s")
                time.sleep(back_off)
                continue
            if resp.status_code >= 500:
                back_off = 2 ** attempt
                print(f"  {resp.status_code} on {path}, retrying in {back_off}s")
                time.sleep(back_off)
                continue
            if resp.status_code != 200:
                raise HootsuiteError(
                    f"GET {path} -> {resp.status_code}: {resp.text[:400]}"
                )
            return resp.json()

        raise HootsuiteError(f"GET {path} failed after 5 attempts")

    # ----- resources --------------------------------------------------------

    def social_profiles(self) -> list[dict]:
        return self._get("/v1/socialProfiles").get("data", [])

    def messages(
        self,
        start: datetime,
        end: datetime,
        social_profile_ids: list[str] | None = None,
    ) -> Iterator[dict]:
        """Yield outbound messages across an arbitrarily wide window."""
        cursor_window = start
        while cursor_window < end:
            chunk_end = min(cursor_window + timedelta(days=MAX_WINDOW_DAYS), end)
            yield from self._messages_window(cursor_window, chunk_end, social_profile_ids)
            cursor_window = chunk_end

    def _messages_window(
        self,
        start: datetime,
        end: datetime,
        social_profile_ids: list[str] | None,
        depth: int = 0,
    ) -> Iterator[dict]:
        """Every message in one window, following the cursor.

        If a window comes back full with no usable cursor, the response has been
        silently truncated and the tail of the window is simply missing. That is
        exactly what happened once TRPL crossed 100 messages in a chunk: posts
        furthest in the future dropped off the calendar with no error anywhere.
        Rather than trust the cursor, detect the truncation and bisect until
        every piece fits under the limit.
        """
        rows: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page = 0
        truncated = False

        while True:
            page += 1
            query: list[tuple[str, str]] = [
                ("startTime", _iso(start)),
                ("endTime", _iso(end)),
                ("limit", str(PAGE_LIMIT)),
                ("includeUnscheduledReviewMsgs", "true"),
            ]
            for pid in social_profile_ids or []:
                query.append(("socialProfileIds", str(pid)))
            if cursor:
                query.append(("cursor", cursor))

            body = self._get("/v1/messages", params=query)
            data = body.get("data") or []
            rows.extend(data)

            cursor = _next_cursor(body)
            if cursor and cursor not in seen_cursors:
                seen_cursors.add(cursor)
                continue

            # A full page with nowhere to go next means there is more behind it.
            if len(data) >= PAGE_LIMIT:
                truncated = True
            break

        span_days = max((end - start).total_seconds() / 86400, 0)
        if truncated and span_days > MIN_WINDOW_DAYS:
            middle = start + (end - start) / 2
            print(f"  {start:%Y-%m-%d}->{end:%Y-%m-%d} hit the {PAGE_LIMIT}-row "
                  f"limit with no cursor; splitting at {middle:%Y-%m-%d}")
            yield from self._messages_window(start, middle, social_profile_ids, depth + 1)
            yield from self._messages_window(middle, end, social_profile_ids, depth + 1)
            return

        if truncated:
            # A single day over the limit cannot be split further.
            print(f"  WARNING: {start:%Y-%m-%d} alone exceeds {PAGE_LIMIT} "
                  f"messages and the API returned no cursor - some are missing")

        print(f"  {start:%Y-%m-%d} -> {end:%Y-%m-%d}: {len(rows)} message(s) "
              f"over {page} page(s)")
        yield from rows

    def media_download_url(self, media_id: str) -> str | None:
        """Resolve a media id to a temporary, pre-signed download URL.

        Returns None when the asset has been purged (Hootsuite deletes media 90
        days after use) or is still transcoding.
        """
        try:
            body = self._get(f"/v1/media/{media_id}")
        except HootsuiteError as exc:
            print(f"  media {media_id} unavailable: {exc}")
            return None
        data = body.get("data") or {}
        if data.get("state") not in (None, "READY"):
            print(f"  media {media_id} not READY (state={data.get('state')})")
            return None
        return data.get("downloadUrl")


def _next_cursor(body: dict) -> str | None:
    """Pull the forward cursor out, wherever this deployment puts it.

    Documented shape is metadata.cursor.next, but the calendar was silently
    losing rows, so accept the other plausible spellings rather than assume.
    """
    meta = body.get("metadata") or {}
    candidates = [
        (meta.get("cursor") or {}).get("next"),
        meta.get("next"),
        meta.get("nextCursor"),
        body.get("next"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
