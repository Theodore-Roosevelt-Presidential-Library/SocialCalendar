# Social Calendar

A read-only web view of the Theodore Roosevelt Presidential Library's upcoming
social media schedule, pulled from Hootsuite and published to
**https://socialcalendar.labs.trlibrary.com/**

Two views over the same data:

- **Month** — a calendar grid, one row per week. One story going out to six
  channels is a *single* row carrying a network icon per channel, not six rows;
  click it to compare how the copy reads on each. Posts group only when they
  are scheduled to the same instant and either came from the same Hootsuite
  message or read as the same story, so genuinely different posts sharing a
  send time stay separate.
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

## The link-in-bio page

`/links/` is a second, separate page built for social profile bios:
**https://socialcalendar.labs.trlibrary.com/links/**

Hootsuite does not push posted links into Hootbio and offers no widget for it,
so this rebuilds the same thing from the calendar snapshot. `build_links.py`
takes recent posts that mention a URL (with or without a scheme), follows the
`ow.ly` shortlink to its real destination, reads that page's own headline and
description, and folds the six per-network variants of one story into a single
card. Up to twenty **published** stories are kept; scheduled ones ride along
as extras for the timed reveal rather than competing for those slots. Posts without a link are skipped, and
anything that failed to send never appears.

`links.json` is an archive, not a snapshot: the calendar only keeps a fortnight
of history, so each build merges its findings with what was published last time
rather than letting a story vanish when its posts age out of that window. The
calendar's media pruner knows about it and will not delete a thumbnail an
archived card still needs.

To backfill more history in one go, run the workflow manually with
`days_back` set to 90 — the archive keeps whatever that turns up.

It is styled to match **hootbio.com/trlibrary** rather than the calendar, so
tapping through from the Hootbio page feels seamless: Gray Sky `#99ADC5`
background, Night Sky `#092A4D` cards, Source Sans 3, 4px corners. Both of those
colours are TRPL brand, so it is on-brand either way.

**Scheduled posts appear on time without a rebuild.** `links.json` ships with
future stories included, and the page holds each one back until its send time
passes, then reveals it. That closes the gap left by a job that only runs twice
a day.

Two things to know about that trade-off:

- `links.json` is publicly readable, so a future story's headline and
  destination are visible before it publishes. The page does not advertise
  this, but it is not hidden either. Everything on this repo's Pages site is
  public by design.
- If a scheduled post fails to send, its card still appears at the scheduled
  moment and stays until the next build corrects it — at most twelve hours.

## The Hootbio card image

`build_cover.py` composes the artwork for the **See Our Latest Posts** card on
Hootbio out of the newest published link thumbnails, and rebuilds it on every
refresh:

- **https://socialcalendar.labs.trlibrary.com/data/cover.jpg** — the 1600×900
  master to upload
- **`/data/cover-preview.png`** — the same thing at 476×268, i.e. exactly what
  Hootbio renders in the card

That slot is 16:9, `object-fit: cover`, 4px corners, and lands at 476×268 on a
desktop — roomy enough that individual stories genuinely read. Default layout is
a six-up mosaic. Others via `--style`: `eight`, `hero` (one large, four small),
`four`, `pair`, `single`, `strip`. When there are not enough linked stories with
imagery, it steps down the ladder automatically rather than padding the frame
with flat colour.

`--mark` adds the TRPL monogram in the corner. Off by default: the card already
sits directly under the TRPL avatar and above a button that says what it is, so
the mark is redundant there and costs a tile.

`--shape avatar` builds the circular 100×100 profile picture instead. That one
*does* carry the monogram by default — at 100px a bare mosaic stops reading as
TRPL to anyone.

Only stories that have already published are used — the artwork must never give
away tomorrow's announcement.

Hootbio has no upload API, so setting it is manual: download the master and
replace the image on the card in Hootbio.

## Brand

Colours and type come from
[`Brand/brand.json`](https://github.com/Theodore-Roosevelt-Presidential-Library/Brand),
and the implementation mirrors
[trphotos.labs.trlibrary.com](https://trphotos.labs.trlibrary.com) so the labs
sites read as one family: Dark Gray header and footer bars, the white wordmark,
Dharma Gothic E in caps for display type, Clearface for body, Frutiger for
labels and captions, Deep Orange for the primary action, Dark Forest for
headings. Fonts load from trlibrary.com; a system fallback stack covers the
gap while they arrive.

One deliberate exception: **post copy inside a preview card stays on the
platform-native font stack**, not Clearface. The point of those cards is to
show what a post will look like on X or Instagram — rendering them in TRPL's
own typography would make the preview lie. Every surface around the card is
brand type.

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
| `site/links/` | The link-in-bio page |
| `scripts/build_links.py` | Resolves shortlinks, groups stories, writes `links.json` |
| `scripts/build_cover.py` | Composes the Hootbio card image and profile picture |
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
