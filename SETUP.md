# Setup

One-time configuration so the calendar refreshes itself. Roughly ten minutes.

Nothing here is reversible-with-consequences — if a step goes wrong, redo it.

---

## 1. Register a Hootsuite developer app

1. Go to **https://hootsuite.com/developers/my-apps** and sign in with the TRPL
   Hootsuite account.
2. Create an app. Name it something obvious, e.g. `TRPL Social Calendar`.
   REST API access is free; no plan upgrade is required.
3. Open the app, then **Security → Rest API**, and add this redirect URI
   *exactly*, including the port and the lack of a trailing slash:

   ```
   http://localhost:8723/callback
   ```

   > Once an app moves to "In Review" or "Launched", Hootsuite locks redirect
   > URIs and you have to email dev.support@hootsuite.com to change them. Set it
   > now while the app is still in draft.

4. Copy the **Client ID** and **Client Secret**.

---

## 2. Create a GitHub token that can write secrets

Hootsuite refresh tokens are **single-use**: every refresh returns a replacement
that has to survive until the next run. The workflow stores it back into a
repository secret, and the built-in `GITHUB_TOKEN` is not allowed to do that —
so it needs a personal access token.

1. **https://github.com/settings/personal-access-tokens/new** (fine-grained).
2. Resource owner: **Theodore-Roosevelt-Presidential-Library**
3. Repository access: **Only select repositories → SocialCalendar**
4. Repository permissions → **Secrets: Read and write**
   (that is the only permission needed)
5. Expiration: pick a date and put a reminder in your calendar. When it expires
   the refresh stops and the workflow opens an issue telling you why.
6. Generate and copy the token.

---

## 3. Authorize the app once, on your laptop

Hootsuite has no machine-to-machine grant for publishing data, so a human has to
click "Allow" one time. From a clone of this repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/bootstrap_auth.py
```

The virtual environment matters on macOS: recent Python builds refuse a plain
`pip install` into the system interpreter ("externally-managed-environment").
`.venv/` is gitignored. Run `deactivate` when you are finished.

The script asks for the Client ID and Secret, opens your browser, and after you
approve prints the three values you need. Leave the terminal open.

---

## 4. Add four repository secrets

**Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `HOOTSUITE_CLIENT_ID` | from step 1 |
| `HOOTSUITE_CLIENT_SECRET` | from step 1 |
| `HOOTSUITE_REFRESH_TOKEN` | printed by step 3 |
| `SECRETS_PAT` | the token from step 2 |

After the first successful run, `HOOTSUITE_REFRESH_TOKEN` is managed
automatically. Do not edit it by hand unless the workflow asks you to.

---

## 5. Turn on Pages and DNS

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. In Cloudflare (or wherever `trlibrary.com` DNS lives), add a CNAME:

   ```
   socialcalendar.labs   →   theodore-roosevelt-presidential-library.github.io
   ```

   If it is a Cloudflare record, set it to **DNS only** (grey cloud) until
   GitHub finishes issuing the certificate, then proxying can be turned back on.
3. `site/CNAME` already contains the hostname, so GitHub picks it up on deploy.
4. Back in **Settings → Pages**, tick **Enforce HTTPS** once the certificate
   shows as issued (usually within about fifteen minutes).

---

## 6. Run it

**Actions → Refresh social calendar → Run workflow.**

The log should read:

```
secret write access confirmed
access token acquired
rotated HOOTSUITE_REFRESH_TOKEN
window: ...
10 social profile(s)
N message(s) total
wrote site/data/calendar.json (nnn KB)
```

After that it runs itself at 6am and 6pm US Central.

---

## When something breaks

The workflow opens a GitHub issue on any scheduled-run failure. The two things
that actually go wrong:

**"The stored refresh token is probably spent or revoked"**
The single-use chain broke — usually because two runs overlapped, or someone
edited the secret by hand. Re-run `python scripts/bootstrap_auth.py` and paste
the new value into `HOOTSUITE_REFRESH_TOKEN`. Nothing else needs to change.

**"SECRETS_PAT was rejected"**
The PAT expired or lost its permission. Make a new one (step 2) and update the
secret. The Hootsuite token is untouched — the script checks GitHub access
*before* it spends the refresh token, precisely so this failure stays cheap.

---

## Running the fetch locally

Useful for debugging. `--local` prints the rotated refresh token instead of
writing it to GitHub, so **you have to paste it back into the secret afterwards**
or the next scheduled run will fail.

```bash
export HOOTSUITE_CLIENT_ID=...
export HOOTSUITE_CLIENT_SECRET=...
export HOOTSUITE_REFRESH_TOKEN=...
python scripts/build_calendar.py --local

# then preview:
cd site && python -m http.server 8080
```
