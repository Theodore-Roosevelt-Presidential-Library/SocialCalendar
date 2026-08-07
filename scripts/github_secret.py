"""
Read/write GitHub Actions repository secrets.

Needed because Hootsuite refresh tokens are single-use: every run consumes one
and gets a replacement, which has to survive until the next run. A GitHub
Actions secret is the only durable, non-public place the workflow can put it.

Requires a fine-grained PAT with Repository permissions -> Secrets: Read and
write, stored as the SECRETS_PAT secret. The built-in GITHUB_TOKEN cannot do
this.
"""

from __future__ import annotations

import base64

import requests
from nacl import encoding, public


class SecretWriteError(RuntimeError):
    pass


class RepoSecrets:
    def __init__(self, repo: str, token: str):
        self.repo = repo  # "owner/name"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _url(self, path: str) -> str:
        return f"https://api.github.com/repos/{self.repo}{path}"

    def preflight(self) -> None:
        """Confirm the PAT can actually write before we burn the refresh token.

        Ordering matters: once the Hootsuite refresh call succeeds the old token
        is dead, so if we discovered a bad PAT afterwards the chain would be
        broken and a human would have to re-authorize. Checking first turns that
        failure mode into a clean, recoverable error.
        """
        resp = self.session.get(self._url("/actions/secrets/public-key"), timeout=30)
        if resp.status_code == 404:
            raise SecretWriteError(
                f"SECRETS_PAT cannot see {self.repo}'s Actions secrets (404). "
                "Check the token is fine-grained, scoped to this repository, and "
                "has 'Secrets: Read and write'."
            )
        if resp.status_code in (401, 403):
            raise SecretWriteError(
                f"SECRETS_PAT was rejected ({resp.status_code}). It is likely "
                "expired or missing the 'Secrets: Read and write' permission."
            )
        if resp.status_code != 200:
            raise SecretWriteError(
                f"Unexpected response fetching the repo public key: "
                f"{resp.status_code} {resp.text[:300]}"
            )
        self._public_key = resp.json()

    def put(self, name: str, value: str) -> None:
        key = getattr(self, "_public_key", None)
        if key is None:
            self.preflight()
            key = self._public_key

        sealed = public.SealedBox(
            public.PublicKey(key["key"].encode("utf-8"), encoding.Base64Encoder())
        ).encrypt(value.encode("utf-8"))

        resp = self.session.put(
            self._url(f"/actions/secrets/{name}"),
            json={
                "encrypted_value": base64.b64encode(sealed).decode("utf-8"),
                "key_id": key["key_id"],
            },
            timeout=30,
        )
        if resp.status_code not in (201, 204):
            raise SecretWriteError(
                f"Failed to write secret {name}: {resp.status_code} "
                f"{resp.text[:300]}"
            )
