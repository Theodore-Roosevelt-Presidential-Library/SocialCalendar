# Social Calendar

A read-only web view of the Theodore Roosevelt Presidential Library's upcoming
social media schedule, pulled from Hootsuite and published to
**https://socialcalendar.labs.trlibrary.com/**

Two views over the same data:

- **Month** — a calendar grid, one row per week, each post shown as a colour-coded
  strip with its thumbnail and send time.
- **Agenda** — a forward-running list from today, with every post rendered as a
  preview that mimics how it will actually look on its network.

Filter by channel, tag, and status; search the copy; click any post for the full
text and metadata.

## How it works

```
Hootsuite REST API
      │   (GitHub Actions, 6am + 6pm US Central)
      ▼
scripts/build_calendar.py
      │   writes site/data/calendar.json + downsized preview images
      ▼
committed to main  ──►  actions/deploy-pages  ──►  socialcalendar.labs.trlibrary.com
```

The site is plain HTML, CSS, and JavaScript with no build step and no
dependencies. Everything it needs is in `site/`; open `site/index.html` through
a local web server and it works.

Preview images are downloaded and committed rather than hot-linked, because
Hootsuite serves media through pre-signed S3 URLs that expire within minutes —
any URL embedded in the page would be dead long before someone loaded it.

## Layout

| Path | What it is |
|---|---|
| `site/index.html`, `app.js`, `styles.css` | The whole front end |
| `site/data/calendar.json` | The published schedule snapshot |
| `site/data/media/` | Downsized preview images (≤1000px, JPEG) |
| `scripts/build_calendar.py` | The scheduled fetch: token rotation → API → JSON |
| `scripts/hootsuite.py` | Hootsuite REST client |
| `scripts/github_secret.py` | Writes the rotated refresh token back to a repo secret |
| `scripts/bootstrap_auth.py` | One-time local OAuth, run once by a human |
| `scripts/seed_from_mcp.py` | Builds the same JSON from a Hootsuite MCP capture |
| `.github/workflows/refresh.yml` | Fetch, commit, deploy |

## Setup

The automated refresh needs a Hootsuite developer app and three repository
secrets. That is a one-time, roughly ten-minute job — see **[SETUP.md](SETUP.md)**.

Until it is done, the workflow still deploys, it just serves whatever snapshot is
committed. The current snapshot was captured through the Hootsuite MCP connector
on 7 August 2026.

## Known limitation: drafts

Hootsuite's public REST API has **no drafts endpoint**. `GET /v1/messages`
returns scheduled, sent, and approval-queue messages only. Content that lives in
Hootsuite as an unpublished draft — which is how a lot of TRPL's `#OTD` content
is currently staged — will not appear once the automated refresh takes over.

Three ways forward, in rough order of effort:

1. **Schedule instead of draft.** A scheduled post can still be edited or
   deleted before it sends, and it shows up in the API immediately.
2. **Ask Hootsuite** whether the Planner/drafts surface behind their MCP
   connector is available as a documented, supported REST endpoint. If it is,
   `scripts/hootsuite.py` is the only file that needs to change.
3. **Re-run the MCP capture** periodically (`scripts/seed_from_mcp.py`) as a
   manual top-up. Workable, but it is not automation.

## Access

The site is public — anyone with the URL can read the upcoming schedule,
including unpublished copy. `noindex` keeps it out of search results, but that is
obscurity, not access control. If that changes, putting Cloudflare Access in
front of the hostname is the cleanest fix and needs no code changes.
