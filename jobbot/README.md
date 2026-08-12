# jobbot — fast part-time job watcher & auto-applier (London / England)

jobbot polls UK job boards at high frequency, spots **new** part-time postings
the moment they appear in the boards' feeds, and reacts instantly:

- **Auto-apply on Reed.co.uk** — one-click apply with your saved Reed profile
  and CV, submitted by a real browser (Playwright) seconds after detection.
- **Amazon warehouse watcher** — polls Amazon's own hiring portal
  (jobsatamazon.co.uk) directly, every 15 s by default, no API key needed.
- **Instant Telegram alert** for every match (including boards it can't
  auto-apply to, e.g. Adzuna results that redirect to employer sites), so you
  can tap "Apply" from your phone immediately.

## How fast is "instant"?

The bot's own reaction time is seconds: each poll is compared against a local
database and any brand-new posting is dispatched immediately (applications and
alerts run concurrently, so nothing queues). The end-to-end delay from
*employer clicks publish* to *application sent* is therefore:

> board indexing delay (usually 1–15 min, outside anyone's control)
> + up to one `poll_seconds` interval + ~2–5 s to apply/notify.

There is no public real-time push feed for UK job boards, so no tool can
guarantee 5–6 seconds from the actual posting moment — but jobbot gets you as
close as polling allows, and being minutes-fast already puts you in the first
handful of applicants.

## Setup

```bash
cd jobbot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # only needed for auto-apply

cp .env.example .env                 # add your API keys (free, links inside)
cp config.example.yaml config.yaml   # set your keywords/locations
```

Get keys (both free, instant signup):

- Reed Jobseeker API: <https://www.reed.co.uk/developers/jobseeker>
- Adzuna API: <https://developer.adzuna.com/>

For Telegram alerts: create a bot with [@BotFather](https://t.me/BotFather),
put the token in `.env`, send your bot any message, then read your `chat_id`
from `https://api.telegram.org/bot<TOKEN>/getUpdates`.

## Usage

```bash
# 1. Test your search — one fetch, prints matches, changes nothing
python -m jobbot --once

# 2. Watch + notify (recommended mode)
python -m jobbot

# 3. Watch + AUTO-APPLY on Reed + notify
python -m jobbot --apply
```

The first poll of each source only records the current listings as a baseline
— it will never mass-apply to the existing backlog. From the second poll on,
anything new triggers the pipeline.

### Auto-apply prerequisites (Reed)

1. Create a Reed account, **complete your profile and upload your CV** on the
   website once — that's what makes listings one-click applyable.
2. Put `REED_EMAIL` / `REED_PASSWORD` in `.env`.
3. Optionally edit `cover_letter.txt` (`{title}`, `{company}`, `{location}`
   are filled in per job).
4. Start with `headless: false` in `config.yaml` to watch it work.

Jobs that use an external application form (redirects off Reed) can't be
one-clicked; those fall back to a Telegram alert. Failures save a screenshot
to `data/screenshots/` for debugging. `apply.max_per_hour` caps automatic
submissions as a safety brake.

## Amazon warehouse jobs (fill within minutes)

Amazon hourly roles (warehouse, sortation centre, delivery station) are posted
on Amazon's own portal — **not** on Reed/Adzuna — and are often gone within
minutes. The `amazon_uk` source watches that portal directly:

- The portal sits behind AWS WAF, so plain HTTP polling gets blocked. jobbot
  keeps one headless browser page open (it passes the WAF check like any
  visitor) and replays the site's own search query in-page every poll —
  roughly a 200 ms call, so a 10–15 s interval is cheap and looks like a
  normal visitor. It needs `playwright install chromium` (same dependency as
  Reed auto-apply).
- Most polls return an **empty list — that's normal**. Amazon UK hiring opens
  in bursts; the bot's job is to be watching the second a burst starts.
- Listings are country-wide (all of the UK). Location/keyword search settings
  don't apply to this source; `include_title`/`exclude_title` filters still do.
- **No auto-apply here**: applying needs your Amazon hiring account and a
  shift-selection step, so speed comes from the instant Telegram alert — tap
  the link, pick a shift, done. Log in to jobsatamazon.co.uk on your phone
  beforehand so the application is 3 taps when the alert lands.

## Searching all of England

Reed's API searches around a named place, so list the cities you care about in
`locations`. Adzuna accepts region names — put `"England"` in `locations` and
it will match country-wide (sorted newest-first).

## Project layout

```
jobbot/
  main.py                 # orchestrator: poll loops, dedupe, dispatch
  config.py               # YAML config + .env secrets
  models.py               # Job dataclass
  store.py                # SQLite: seen jobs + application log
  filters.py              # include/exclude/part-time/freshness filters
  sources/reed.py         # Reed Jobseeker API
  sources/adzuna.py       # Adzuna API (best posting timestamps)
  notify.py               # Telegram alerts
  applier/reed_playwright.py  # browser one-click apply on Reed
```

## Fair-use notes

- Keep `poll_seconds` reasonable (default 30 s) — hammering the APIs will get
  your key throttled or banned, which makes you *slower*, not faster.
- Automated applying may breach a job board's terms of service; the Reed
  applier drives your own logged-in account exactly like a very fast human,
  but use it at your own discretion and keep `max_per_hour` sensible.
- Review what the bot applies to (`data/jobbot.db` `applications` table, plus
  Telegram messages tell you what was auto-applied).
