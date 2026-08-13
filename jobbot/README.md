# jobbot — fast part-time job watcher & auto-applier (London / England)

jobbot polls UK job boards at high frequency, spots **new** part-time postings
the moment they appear in the boards' feeds, and reacts instantly:

- **Auto-apply on Reed.co.uk** — one-click apply with your saved Reed profile
  and CV, submitted by a real browser (Playwright) seconds after detection.
- **Amazon warehouse watcher** — polls Amazon's own hiring portal
  (jobsatamazon.co.uk) directly, every 15 s by default, no API key needed.
- **Direct company-portal watchers** — watch ANY employer's own careers page
  (McDonald's, Primark, Sainsbury's, Tesco, Costa… included; add more with a
  3-line config entry). No aggregator delay, no API key.
- **Telegram group watcher** — if you're in a Telegram group that posts job
  links (e.g. Amazon warehouse alert groups), the bot reads new messages the
  second they land (push, ~1-2 s) and fires on any job link in them.
- **Amazon auto-apply (experimental)** — with a one-time login, the bot can
  click through the jobsatamazon.co.uk apply flow itself the moment a role
  appears, instead of just alerting you.
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
- Alerts fire instantly; with the experimental [Amazon auto-apply](#amazon-auto-apply-experimental)
  enabled, the bot even submits the application itself. Either way, log in to
  jobsatamazon.co.uk beforehand so the final steps are instant.
- Getting listings from a Telegram group instead? See
  [Watching a Telegram job-alert group](#watching-a-telegram-job-alert-group-fastest-trigger-of-all)
  — it's an even faster trigger and feeds the same apply pipeline.

## Watching a Telegram job-alert group (fastest trigger of all)

If listings reach you through a Telegram group (common for Amazon warehouse
roles — and they're gone in a minute), let the bot read the group directly.
Unlike every polling source, this is **push**: the bot reacts ~1–2 seconds
after the message is posted.

One-time setup:

1. Go to <https://my.telegram.org> → *API development tools* → create an app,
   and put `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` in `.env`. (These identify
   *your* Telegram account — group reading can't be done with a BotFather
   bot, since bots only see groups they're added to as members.)
2. Run `python -m jobbot telegram-login` — enter your phone number and the
   code Telegram sends you. It then prints all your chats with their ids.
3. Put the group name(s) or id(s) in `telegram_watch.chats` in `config.yaml`
   and set `enabled: true`. An empty `chats` list watches everything.

Any `jobsatamazon.co.uk` link in a message becomes an Amazon job (deduped
against the portal watcher, so you never double-apply); other job links get
alerted as-is. Group messages skip the keyword filters — the group already
curated them, and speed matters more.

## Amazon auto-apply (experimental)

For listings that vanish in a minute, an alert can still be too slow. With
this enabled the bot applies by itself:

1. `python -m jobbot amazon-login` — a browser window opens; log in to your
   Amazon jobs account (they send a PIN — that's why this one step is
   manual), then close the window. The logged-in session is saved to
   `data/amazon_profile` and reused from then on. **Complete your candidate
   profile on the site first** so applications don't stall on missing info.
2. Set `apply.amazon_enabled: true` in `config.yaml` (start with
   `headless: false` so you can watch it), and run `python -m jobbot`.
3. When a new Amazon job arrives (from the portal watcher or a Telegram
   group), the bot opens it in your logged-in profile and clicks through
   shift selection → apply → confirmation.

Honest caveats: Amazon changes this flow often and sometimes adds checks a
bot can't pass, so treat it as a head start rather than a guarantee — every
attempt is screenshotted to `data/screenshots/`, the Telegram alert is always
sent too, and if the click-through stalls you finish the last step by hand on
a page that's already loaded and logged in. Automating applications is also
against most sites' terms of service — including Amazon's — so use it at your
own discretion and keep `max_per_hour` sensible.

## Watching any company's own careers portal

Big employers post on their own sites first (and some, like Amazon, *only*
there). The `portals:` section of `config.yaml` lets you watch any of them
directly — the bot loads the search page in a headless browser (so
JavaScript-rendered lists and bot checks behave like a normal visitor),
collects every job link on it, and alerts the moment a link it has never seen
appears.

Adding a new company takes three lines:

1. Open the company's careers **search results** page in your browser, set
   your location filter, and copy that URL into `url`.
2. Click any job on it and look at the job page's address — put the
   distinctive part of it into `link_pattern` (it's a regex). Example: Greggs
   job pages look like `.../vacancies/12345`, so use `"/vacancies/"`.
3. Give it a `name` and a `poll_seconds` (a poll is a full page load, so stay
   ≥ 30 s to be a polite visitor).

Notes:

- List pages rarely say part-time/full-time, so portal jobs are never dropped
  by the `part_time_only` filter — use `exclude_title` to cut obvious
  full-time-only titles, and check the alert before applying.
- Auto-apply doesn't run on portal jobs (every company's form is different);
  you get the instant Telegram alert with the direct link instead.
- If a portal changes its site layout, the worst case is the watcher logs
  errors or matches nothing — fix the `url`/`link_pattern` and restart.

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
