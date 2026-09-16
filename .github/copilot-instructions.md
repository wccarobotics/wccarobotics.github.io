# Copilot Instructions — WCCA Robotics Website

## Build & Serve

```bash
bundle exec jekyll build          # build site to _site/
bundle exec jekyll serve          # local dev server at http://localhost:4000
```

No test suite, linter, or CI pipeline exists.

## Architecture

Jekyll site hosted on GitHub Pages. Three layouts: `default.html` (shell with header/footer/JS), `page.html` (wraps in `.page-content`), `home.html` (no wrapper — used only by `index.md`).

All CSS is in `assets/css/style.css` (single file, no preprocessor). All JS is in `assets/js/team-highlight.js` (team number click-to-highlight on tournament pages). Both are loaded site-wide from `default.html`.

### Content areas

- **Team pages**: `ftc.md`, `fll.md` — team descriptions, robot photos, competition history
- **Tournament results**: `tournaments/ftc/` and `tournaments/fll/` — match tables with timestamped YouTube links, rankings, awards. Each subfolder has an `index.md` listing page. Old URLs at `tournaments/*.md` are redirect stubs.
- **Innovation projects**: `innovation-cocoplus.md`, `innovation-backpack.md` — FLL innovation project writeups
- **Support pages**: `support.md`, `about.md`, `contact.md`, `ftc-scouting.md`, `marcus.md`
- **Tournament info**: `tournaments/ftc/2026-FTC-Championship-Info.md`, `tournaments/fll/2026-FLL-Florida-Qualifier-Info.md` — parent-facing event logistics (not results)

### Navigation

Header nav is hardcoded in `_includes/header.html`. FTC and FLL are both dropdowns. Active state is determined by `page.url` matching patterns (e.g., `/ftc`, `/tournaments/ftc`).

### Skills (`.claude/skills/`)

Skills are AI agent playbooks — detailed SKILL.md files with step-by-step workflows, heuristics, and output templates. They are NOT CI workflows. Four exist:

- `fll-tournament-analyzer` — creates FLL tournament result pages from YouTube livestream + FLL Gameday API
- `ftc-tournament-analyzer` — creates FTC tournament result pages from YouTube livestream + FTC Events website
- `ftc-scorecard-generator` — screenshots FTC Events pages into branded 1920×1080 PNGs using Playwright
- `ftc-scouting-processor` — reads photos of handwritten scouting forms and updates the scouting pages

They live in `.claude/skills/` because both Claude Code and GitHub Copilot discover
repository skills from that path — Copilot also accepts `.github/skills/`, but Claude Code
does not.

### Reference data

`decode_manual_sections/` contains the FTC DECODE Competition Manual split into ~88 text files by section. Use these to answer game rules questions accurately.

## Conventions

### HTML/CSS classes in markdown pages

Pages mix markdown with raw HTML. Common patterns:

```html
<div class="video-container">
  <iframe src="https://www.youtube.com/embed/VIDEO_ID" allowfullscreen></iframe>
</div>

<div class="photo-grid">
  <a href="/assets/images/photo.jpg" target="_blank"><img src="/assets/images/photo.jpg" alt="Description"></a>
</div>

<div class="highlight-box">
  <h3>Title</h3>
  <p>Content</p>
</div>
```

- `video-container` — responsive 16:9 YouTube embed
- `video-container-vertical` — 9:16 vertical video (used in `video-grid` pairs)
- `photo-grid` — auto-fit grid of images with 4:3 aspect ratio
- `highlight-box` — callout box with blue left border
- `btn btn-blue` — blue action button
- `tournament-card` — card with blue left border for tournament listings
- `team-logo` — constrained logo display (max 400px)
- `{: .portrait}` / `{: .portrait-sm}` — kramdown attribute for centered portrait images

### Tournament page format

**FTC** (alliance-based, competitive):
- Sections in order: Qualification Matches → Qualification Rankings → Playoff Matches (with Alliances table + Bracket) → Awards Ceremony
- Match tables have columns: Match, Red Alliance 1, Red Alliance 2, Red Score, Blue Alliance 1, Blue Alliance 2, Blue Score, Video Link
- Winning score is **bold**
- Awards section uses `### Award Name — [timestamp](link)` headings with bullet lists

**FLL** (independent scoring, round-based):
- Sections in order: Round 1 → Round 2 → Round 3 → Robot Game Rankings → Awards Ceremony
- Match tables have columns: Team A, Points Scored, Team B, Points Scored, Video Link
- Surrogate matches use `*(surrogate)*` with `—` for score; solo matches use `— | —`
- Awards are nested bullet lists with timestamped links

### Team highlighting

`assets/js/team-highlight.js` automatically wraps 4-5 digit team numbers in `<span class="team-ref" data-team="NNNNN">` within table cells and list items (including inside links). Clicking highlights all occurrences. No special markup needed in markdown — just write `12345 Team Name` naturally.

### Video links

- Livestream videos: `https://www.youtube.com/live/VIDEO_ID?t=SECONDS`
- Uploaded videos: `https://www.youtube.com/watch?v=VIDEO_ID&t=SECONDS`

### FTC Events data

The FTC API at `ftc-api.firstinspires.org` provides structured JSON for matches, rankings, teams, and awards. Credentials are stored in `ftc-api-credentials.json` (git-ignored). If this file doesn't exist on the current machine, ask the user for their auth key and create it:

```json
{
  "username": "dsplaisted",
  "auth_key": "YOUR_AUTH_KEY_HERE"
}
```

To authenticate:

```python
import json, base64
with open('ftc-api-credentials.json') as f:
    creds = json.load(f)
token = base64.b64encode((creds['username'] + ':' + creds['auth_key']).encode()).decode()
headers = {'Authorization': 'Basic ' + token}
```

API base URL: `https://ftc-api.firstinspires.org/v2.0/{season}/`
- `matches/{event_code}` — match results
- `rankings/{event_code}` — rankings
- `teams?eventCode={event_code}` — team list
- `awards/{event_code}` — awards

Season code is the starting year (2024 = 2024-25 season).

Fallback: if credentials are missing, scrape `ftc-events.firstinspires.org` instead. URL patterns: `/{season}/{event_code}/qualifications`, `/rankings`, `/playoffs`, `/awards`.

When using API data on pages, include an attribution link: `<small>Match data provided by the [FIRST Tech Challenge Events API](https://ftc-events.firstinspires.org/services/API).</small>`

### FTC Scout API (OPR and stats — no auth needed)

FTC Scout provides OPR and other derived stats. No authentication required.

- Team stats at an event: `https://api.ftcscout.org/rest/v1/events/{season}/{event_code}/teams`
- Team quick stats: `https://api.ftcscout.org/rest/v1/teams/{number}/quick-stats?season={season}`
- Event matches: `https://api.ftcscout.org/rest/v1/events/{season}/{event_code}/matches`

### Python dependencies for skills

```bash
pip install yt-dlp                    # YouTube caption/audio download
pip install faster-whisper            # speech recognition (when no captions)
pip install playwright Pillow numpy   # scorecard generator
python -m playwright install chromium
pip install pyicloud                  # iCloud Photos access (scouting form photos)
pip install pillow-heif               # HEIC image conversion
```
