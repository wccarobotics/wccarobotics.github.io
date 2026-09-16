---
name: ftc-scouting-processor
description: Process FTC scouting form photos and robot images during a tournament. Reads handwritten scouting forms, extracts data, and updates scouting pages with match results, team stats, and robot photos. Use this skill when asked to process scouting data from photos or update scouting pages during a tournament.
---

# FTC Scouting Processor

This skill processes photos of handwritten scouting forms and robot images taken during an FTC tournament. It extracts data from the forms, updates the scouting summary and team detail pages, and manages robot photos.

## When to use this skill

- When the user provides photos of filled-out scouting forms
- When the user provides photos of robots at a tournament
- When asked to update scouting pages with new data
- When setting up scouting pages for a new tournament

## Required inputs

1. **Scouting form photos** — photos of filled-out paper scouting forms (HEIC, JPG, or PNG)
2. **Event info** — FTC Events URL for the tournament (for match schedules, rankings, scores)

Optional:
3. **Robot photos** — photos of robots at the tournament, with team number visible on the nameplate
4. **Handwritten robot notes** — photos of handwritten notes about robots (observations, capabilities, strategy notes taken before or after qualification matches)
5. **Scouting data folder** — a folder to watch for new photos (e.g., `C:\Users\Daniel\OneDrive\Documents\Scouting`)

## Setup for a new tournament

### Step 1: Create the scouting pages

Create the following files:

- `scouting/index.md` — tournament overview with teams table and match schedule
- `scouting/scouting-data.json` — raw scouting data store

Fetch match schedule and rankings from FTC Events:
- `https://ftc-events.firstinspires.org/{season}/{event_code}/qualifications`
- `https://ftc-events.firstinspires.org/{season}/{event_code}/rankings`

### Step 2: Build the initial teams table

The teams table combines rankings and scouting data in one view:

```markdown
## Teams

| Team | OPR | W-L-T | Avg Auto | Avg Teleop | Teleop Acc. |
| ---- | --- | ----- | -------- | ---------- | ----------- |
| [TEAM_NUM TEAM_NAME](/scouting/TEAM_NUM) | OPR | W-L-T | auto data | teleop data | accuracy |
```

Teams with scouting data link to their detail page. Scouting columns are blank until data comes in.

Auto column format:
- If team has auto from one position only: `~6 pts (near only)`
- If team has auto from both: `~6 pts`
- If team has no auto: `No auto`

### Step 3: Build the match schedule

```markdown
## Match Schedule & Results

| Match | Red Alliance | Blue Alliance | Score | Video |
| ----- | ------------ | ------------- | ----- | ----- |
| Q1 | TEAM / TEAM | TEAM / TEAM | **SCORE** – SCORE | [H:MM:SS](URL&t=SECONDS) |
```

Update scores as results come in from FTC Events. The Video column links to the match start in the livestream — see "Finding match timestamps in a livestream" below. Omit the Video column if no livestream URL is available.

## Processing scouting forms

### Step 1: Convert photos if needed

HEIC files (from iPhones) need conversion:

```python
from pillow_heif import register_heif_opener
from PIL import Image
register_heif_opener()
img = Image.open('photo.heic')
img.save('photo.jpg', quality=85)
```

Install if needed: `pip install pillow-heif`

### Step 2: Read the form

View the photo and extract all fields from the scouting form. The form uses circle-style options (circle the chosen value) and ✓/✗ tallies for shot tracking.

**Form fields to extract:**

Header:
- Match #
- Team #
- Team name
- Alliance (Red / Blue)
- Scout name

Autonomous:
- Start position (Near / Far)
- Moved? (Yes / No)
- Leave pts? (Yes / No)
- Auto shots (count ✓ and ✗ marks separately)

Teleop:
- Teleop shots (count ✓ and ✗ marks separately)
- Shot from (Near / Far / Both)
- Where in near zone (freeform text)
- Cycle speed (Fast / Med / Slow)
- Played defense? (Yes / No)
- Base? (None / Partial / Full)
- Response to defense (freeform text)

Robot Details:
- Drive type (Tank / Mecanum / Other)
- Intake? (Yes / No)

Overall:
- Broke down? (Yes / No)
- Driver skill (Excellent / Good / Needs work)
- Want as alliance partner? (Def / Maybe / No)
- Notes (freeform text)

**Important rules for reading forms:**
- Blank/uncircled fields should be recorded as `null`, NOT defaulted to any value. Treat blank as unknown.
- For shot tallies, ✓ = scored, ✗ = missed. Count each separately.
- Circled options: look for ink loops around the printed text
- Handwritten notes may be hard to read — do your best, note uncertainty with [?]

### Step 3: Update scouting-data.json

Add the extracted data as a new entry in the `scouting` array in `scouting/scouting-data.json`.

### Step 4: Update or create team detail page

Create `scouting/TEAM_NUM.md` if it doesn't exist, or update it with new match data.

**Team detail page format:**

```markdown
---
layout: page
title: "Scouting — TEAM_NUM TEAM_NAME"
---

# TEAM_NUM TEAM_NAME

[← Back to scouting overview](/scouting/)

![TEAM_NUM TEAM_NAME robot](/assets/images/scouting/TEAM_NUM-robot.jpg)
(only if a robot photo exists)

## Robot Details

| | |
| --- | --- |
| Drive type | TYPE |
| Intake | Yes/No — additional details |

## EVENT_NAME (DATE)

### Summary

| Stat | Value |
| ---- | ----- |
| Matches scouted | N |
| Auto (near start) | X/Y shots (~Z pts), leave/no leave (N matches) |
| Auto (far start) | X/Y shots (~Z pts) or "Did not run auto" (N matches) |
| Teleop accuracy | X/Y (Z%), ~W pts avg |
| Leave points | N of M matches |
| Base | status per match or "unknown" if not recorded |
| Cycle speed | Fast/Med/Slow |
| Played defense | Yes/No |

### Scouting Notes

- Compiled notable observations from forms at this event

### Match Details

#### Match N — ALLIANCE Alliance (Won/Lost SCORE–SCORE)

*Scout: NAME*

**Autonomous:** Started near/far. Details. Shots: ✓✗ (X/Y, ~Z pts)

**Teleop:** Shots: ✓✗ (X/Y, ~Z pts). Shot from zone. Cycle: speed. Defense: details. Base: status.

**Notes:** Any notes from the form.

## PREVIOUS_EVENT_NAME (DATE)

(same structure repeated per event, most recent first)
```

**Auto stats should be split by starting position** (near vs far) in the summary. If a team only has auto from one position, show that clearly. If a team chose not to run auto (e.g., let their alliance partner run instead), note that — it's different from not having an auto.

**Scoring points estimation:** Each made shot is ~3 pts. Use this to estimate auto and teleop points from shot counts. Show as approximate (~) since we can't distinguish classified from overflow by observation.

### Step 5: Update the scouting index

Update the team's row in the Teams table in `scouting/index.md`:
- Add a link to the team detail page
- Fill in W-L-T, Avg Auto (with near/far note if only one position), Avg Teleop, and Teleop Accuracy
- Update rankings if they've changed

## Processing robot photos

### Step 1: Identify the team

Look for the team number on the robot's nameplate or team sign. FTC teams are required to have their number displayed on two sides of the robot.

### Step 2: Crop and save the photo

Crop the photo to focus on the robot, removing excess background. Save to `assets/images/scouting/`:

```
assets/images/scouting/TEAM_NUM-robot.jpg
```

Use JPEG at quality 85 for reasonable file size. Resize if the image is very large (max ~1200px wide).

Create the `assets/images/scouting/` directory if it doesn't exist.

### Step 3: Add to team detail page

Add the photo to the team's scouting page near the top, after the title and back link:

```markdown
![TEAM_NUM TEAM_NAME robot](/assets/images/scouting/TEAM_NUM-robot.jpg)
```

Typically one photo per team is sufficient. If a second photo arrives:
- If it's a better quality photo of the same view, replace the existing one
- If it shows a different useful angle (e.g., front view vs intake close-up), place them side-by-side using a photo grid:

```html
<div class="photo-grid">
  <img src="/assets/images/scouting/TEAM_NUM-robot-1.jpg" alt="TEAM_NAME robot">
  <img src="/assets/images/scouting/TEAM_NUM-robot-2.jpg" alt="TEAM_NAME robot intake">
</div>
```

Otherwise, keep the better photo and skip the duplicate.

## Processing handwritten robot notes

These are photos of handwritten notes about robots — observations about capabilities, mechanisms, strategy, strengths, or weaknesses. They may be taken during pit scouting before qualifications start, during matches, or after the event. Notes may cover one team or multiple teams on the same page.

### Step 1: Read the notes

Examine the photo and transcribe all the handwritten notes. Identify which team(s) the notes refer to — look for team numbers written on the page. If multiple teams are covered, separate the notes by team.

### Step 2: Add to team scouting page(s)

Add the observations to each team's scouting page under the **Scouting Notes** section for the current event. Integrate with any existing notes — don't duplicate information that's already there from scouting forms.

Format the notes as bullet points summarizing the key observations. Use the original wording where it's clear, but clean up abbreviations and shorthand into readable text. For example:
- "fast intake, can grab from wall" → "Fast intake — can grab samples from the wall"
- "no auto" → "Does not run autonomous"
- "good at defense, blocks well" → "Strong defensive play — effective at blocking"

If the notes mention capabilities not captured by scouting forms (e.g., pit scouting observations about mechanisms, build quality, or strategy), these are especially valuable — make sure they're included.

### Step 3: Commit and push

Commit the updated scouting page(s) and push.

## Updating rankings, scores, and OPR

Periodically during the tournament, update data from the FTC Events API. See authentication details in `.github/copilot-instructions.md`.

- `https://ftc-api.firstinspires.org/v2.0/{season}/matches/{event_code}` — match results
- `https://ftc-api.firstinspires.org/v2.0/{season}/rankings/{event_code}` — rankings

Fallback: scrape `ftc-events.firstinspires.org` if credentials are missing.

### OPR Calculation

Calculate OPR (Offensive Power Rating) ourselves from the FTC API match data rather than relying on FTC Scout. Use **no-penalty scores** for a cleaner measure of what teams actually do.

```python
import numpy as np
import json, urllib.request, base64

# Authenticate with FTC API
with open('ftc-api-credentials.json') as f:
    creds = json.load(f)
token = base64.b64encode((creds['username'] + ':' + creds['auth_key']).encode()).decode()
headers = {'Authorization': 'Basic ' + token}

# Fetch matches
req = urllib.request.Request(
    'https://ftc-api.firstinspires.org/v2.0/{season}/matches/{event_code}',
    headers=headers)
matches = json.loads(urllib.request.urlopen(req).read())['matches']

# Build team list from qualification matches
teams = sorted(set(
    t['teamNumber'] for m in matches if m['tournamentLevel'] == 'QUALIFICATION'
    for t in m['teams']
))
team_idx = {t: i for i, t in enumerate(teams)}

# Build matrix A and score vector b
# Use no-penalty scores: subtract OPPONENT's foul points from your final score
# scoreRedFoul = fouls committed BY red (added to blue's score)
# scoreBlueFoul = fouls committed BY blue (added to red's score)
# So: no-penalty red score = scoreRedFinal - scoreBlueFoul
A_rows, b_vals = [], []
for m in matches:
    if m['tournamentLevel'] != 'QUALIFICATION':
        continue
    for color, opp in [('Red', 'Blue'), ('Blue', 'Red')]:
        row = [0] * len(teams)
        for t in m['teams']:
            if t['station'].startswith(color):
                row[team_idx[t['teamNumber']]] = 1
        A_rows.append(row)
        # Subtract opponent's committed foul points (which were added to our score)
        score = m[f'score{color}Final'] - m.get(f'score{opp}Foul', 0)
        b_vals.append(score)

A = np.array(A_rows, dtype=float)
b = np.array(b_vals, dtype=float)

# Solve via least squares
opr = np.linalg.solve(A.T @ A, A.T @ b)
team_opr = {teams[i]: round(opr[i], 1) for i in range(len(teams))}
```

**Important:** `scoreRedFoul` means fouls committed BY red (these points are added to BLUE's score). To get no-penalty red score, subtract `scoreBlueFoul` (opponent's fouls) from `scoreRedFinal`. Do NOT subtract `scoreRedFoul` — that's the team's own committed fouls, not the foul bonus they received.

Display OPR rounded to whole numbers on scouting pages. Sort the teams table by OPR descending.

For teams at events we haven't attended but that are in the upcoming tournament, use FTC Scout's quick-stats API (no auth needed) as a pre-tournament baseline:
```
GET https://api.ftcscout.org/rest/v1/teams/{number}/quick-stats?season={season}
```

## Finding match timestamps in a livestream

When a livestream URL is available, find the timestamp for each new match in the video using Playwright-based frame capture. This uses the same approach as the FTC Tournament Analyzer skill. The scouting watcher automatically finds the livestream URL by searching the site's markdown files for pages that reference the event code (e.g., the tournament info page).

### How it works

FTC tournament livestreams display a match overlay graphic at the bottom of the screen showing:
- Match type and number (e.g., "Qualification 4 of 25")
- Team numbers for both alliances
- A countdown timer

When the scouting watcher detects new match results from the FTC API:

1. Open the livestream in headless Playwright (or reuse an existing session)
2. The match just finished, so search backward from the live edge in 2-minute chunks
3. Capture a frame at each position and examine it for the match overlay
4. When the target match is found (match number and team numbers match), read the timer
5. Calculate the match start time:
   - Auto period: `match_start = frame_position - (30 - auto_remaining)`
   - Teleop period: `match_start = frame_position - (38 + 120 - teleop_remaining)`
6. Subtract ~5 seconds to link to the pre-match countdown
7. Add the timestamped link to the Video column in the match schedule table

### Frame capture code

```python
from playwright.sync_api import sync_playwright
import time

def capture_frame(page, target_seconds, outfile):
    """Seek to target_seconds and screenshot the video element."""
    page.evaluate(f"document.querySelector('video').currentTime = {target_seconds}")
    time.sleep(3)
    actual = page.evaluate("document.querySelector('video').currentTime")
    page.query_selector("video").screenshot(path=outfile)
    return actual
```

### Timestamp display format

Format the video link as `H:MM:SS` or `M:SS` for the display text, with the link pointing to `VIDEO_URL&t=SECONDS`:

```markdown
| Q5 | 32314 / 27795 | 24813 / 23958 | **45** – 30 | [1:23:45](https://www.youtube.com/watch?v=VIDEO_ID&t=5025) |
```

For full details on the frame capture approach (Playwright setup, overlay reading, scanning strategies), see the [FTC Tournament Analyzer skill](/.claude/skills/ftc-tournament-analyzer/SKILL.md), Step 2.

## Batch processing

When given a folder of photos, process all new files:

1. List all files in the folder
2. Compare against already-processed files (tracked in `scouting-data.json` or by filename)
3. For each new file:
   - If it looks like a scouting form (paper with printed form fields), extract scouting data
   - If it looks like a robot photo (robot in a pit or on a field), identify team and save as robot photo
4. Update all affected team pages and the scouting index

## Multi-event data

Scouting data accumulates across events within a season. The same team pages and summary table carry forward from one tournament to the next.

### Data structure

`scouting-data.json` tracks which event each observation came from:

```json
{
  "events": {
    "USARLRAS": {
      "name": "Adventist Robotics Carolina Scrimmage",
      "friendly_id": "2026-nc-scrimmage",
      "date": "2026-03-01"
    },
    "USARLCMP": {
      "name": "Adventist Robotics League Championship",
      "friendly_id": "2026-championship",
      "date": "2026-04-12"
    }
  },
  "scouting": [
    { "event_code": "USARLRAS", "match": 2, "team": 27795, ... },
    { "event_code": "USARLCMP", "match": 1, "team": 27795, ... }
  ]
}
```

### Team detail pages

Keep data separate by event with headings and per-event summaries:

```markdown
## Carolina Scrimmage (March 1, 2026)

### Summary

| Stat | Value |
| ---- | ----- |
| Matches scouted | 2 |
| Auto (near start) | 2/2 shots (~6 pts), no leave (1 match) |
...

### Match Details

#### Match 2 — Red Alliance (Lost 30–39)
...
```

Do NOT aggregate stats across events — robots change between tournaments.

### Scouting index teams table

The teams table on `scouting/index.md` shows scouting data for each team, but only from one event at a time:
- If we have scouting data from the **current event**, show that
- If we only have data from a **previous event**, show that instead (with a note like "from NC Scrimmage")
- Once we get current event data for a team, replace the previous event data in the table

### Transitioning to a new tournament

When setting up for a new tournament:
1. Keep existing team pages and data — don't delete
2. Update `scouting/index.md` with the new event's match schedule and rankings
3. Add the new event to `scouting-data.json` events section
4. New scouting entries get the new event code
5. Teams table shows current event rankings but scouting data from all events

### Archiving

When data gets too large or a season ends, archive to `scouting/archive/FRIENDLY_ID/`:
- Copy `index.md` and team pages
- The archived version is read-only

## Live tournament photo polling

During a tournament, run the scouting watcher script as a background process:

```bash
python .claude/skills/ftc-scouting-processor/scouting_watcher.py --event USARLCMP --season 2025
python .claude/skills/ftc-scouting-processor/scouting_watcher.py --event USARLCMP --season 2025 --check 5
```

This script:
1. Connects to iCloud (may prompt for 2FA on first run)
2. Polls every 30 seconds for:
   - **Match schedule** — checks if qualification pairings have been posted (one-time, stops checking after found)
   - **New photos** from iCloud (skips movies)
   - **New match results** from the FTC API (if `--event` and `--season` are specified)
3. Downloads new photos to `scouting/incoming/` (git-ignored)
4. Invokes Copilot CLI to:
   - Post the match schedule when it becomes available
   - Process scouting form photos, robot photos, and handwritten robot notes
   - Update match results, rankings, and OPR when new matches are scored
   - Find the livestream URL from the site's tournament info pages, find match timestamps, and add Video links to the match table

**Session reuse**: All Copilot invocations share a single named session (`scouting-watcher`). The first invocation creates the session; subsequent invocations resume it with `--resume`. This means Copilot retains context about the event, team list, scouting data structure, and page formats across all photos and match updates — no redundant file reading or re-learning conventions.

Copilot will determine what type of photo it is:
- **Scouting form** — read the form, update data and pages, commit and push
- **Robot photo** — identify team number, save to team's page, commit and push
- **Handwritten robot notes** — read the notes, add observations to the appropriate team scouting page(s), commit and push
- **Unrelated photo** — skip it (iCloud includes all photos, not just scouting ones)

Use `--check N` to limit how many recent photos are checked each poll. Set this low (e.g., 5) once the tournament starts so it doesn't reprocess older photos.

The watcher tracks processed filenames in `scouting/incoming/watcher_state.json` to avoid reprocessing.

### Handling duplicate and updated photos

Track processed photos by their iCloud filename in `scouting-data.json` to avoid re-downloading the same file:

```json
{
  "processed_photos": ["IMG_4400.HEIC", "IMG_4401.HEIC"],
  ...
}
```

If a **new photo** (different filename) contains data for an existing match + team combo:
- It may be a **clearer photo** of the same form — update any fields that were previously hard to read
- It may be from a **different scout** watching the same team — merge the data, filling in blanks from either form. If values disagree, note the discrepancy.
- Record both scout names if multiple scouts contributed data for the same match+team

## Getting photos from iCloud

Photos taken on the user's iPhone can be accessed programmatically via pyicloud. The session persists ~2 months after initial 2FA.

### Authentication

Credentials are stored in `icloud-credentials.json` (git-ignored). If this file doesn't exist on the current machine, ask the user for their Apple ID and password and create it:

```json
{
  "apple_id": "YOUR_APPLE_ID",
  "password": "YOUR_PASSWORD_HERE"
}
```

```python
from pyicloud import PyiCloudService
import json

with open('icloud-credentials.json') as f:
    creds = json.load(f)

api = PyiCloudService(creds['apple_id'], creds['password'])

if api.requires_2fa:
    api.request_2fa_code()  # MUST call this explicitly to trigger the 2FA prompt
    code = input('Enter 2FA code: ')
    api.validate_2fa_code(code)
    api.trust_session()

# After trusting, subsequent logins won't need 2FA
```

**Critical:** Just checking `requires_2fa` does NOT send a code to the user's device. You must call `request_2fa_code()` explicitly.

### Downloading recent photos

**Important:** Use index-based access (`all_photos[i]`), NOT iteration. Iteration goes oldest-first, but indexing respects newest-first sort order.

```python
all_photos = api.photos.all
# Index 0 = most recently added photo
for i in range(10):  # check last 10 photos
    p = all_photos[i]
    if p.added_date < cutoff_date:
        break
    data = p.download()
    with open(p.filename, 'wb') as f:
        f.write(data)
```

### Dependencies

```bash
pip install pyicloud  # v2.5.0+ from timlaing/pyicloud fork
```

## Key conventions

- All scouting pages live in `scouting/`
- Team detail pages are `scouting/TEAM_NUM.md`
- Robot photos go in `assets/images/scouting/TEAM_NUM-robot.jpg`
- Raw data is stored in `scouting/scouting-data.json`
- Blank form fields = `null` in JSON, shown as "unknown" or "not recorded" on pages — never default to a value
- The scouting guide is at `scouting/scouting-guide.md` and the printable form is at `scouting/scouting-form.html` — don't modify these during a tournament
- Shot points are estimated at ~3 pts per made shot (approximate since we can't distinguish classified from overflow by observation)
- The scouting index page (`scouting/index.md`) has a combined Teams table at the top (rankings + scouting data) followed by the match schedule
- Include an attribution link at the bottom of pages using API data: `<small>Match data provided by the [FIRST Tech Challenge Events API](https://ftc-events.firstinspires.org/services/API).</small>`

## Dependencies

```bash
pip install pillow-heif   # for HEIC photo conversion (iPhone photos)
pip install Pillow         # for image processing and cropping
pip install numpy          # for OPR calculation
pip install pyicloud       # for iCloud Photos access
pip install playwright     # for livestream frame capture
# python -m playwright install chromium
```
