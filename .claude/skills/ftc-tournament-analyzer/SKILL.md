---
name: ftc-tournament-analyzer
description: Analyze an FTC tournament livestream video to find match timestamps, fetch scores from FTC Events, and generate a markdown page documenting all matches, rankings, and awards. Use this skill when asked to create a tournament summary page from an FTC livestream video.
---

# FTC Tournament Analyzer

This skill analyzes an FTC (FIRST Tech Challenge) tournament livestream video to produce a markdown page documenting every match with timestamped video links, scores, rankings, alliances, playoff bracket, and awards — following the format used in [2025-Adventist-Robotics-League-Championship-FTC.md](https://github.com/wccarobotics/wccarobotics.github.io/blob/main/tournaments/ftc/2025-Adventist-Robotics-League-Championship-FTC.md).

## When to use this skill

- When the user provides an FTC tournament livestream URL and asks to document it
- When the user wants match timestamps extracted from an FTC video
- When creating a tournament summary markdown page for an FTC event

## Required inputs

1. **YouTube video URL** — the full tournament livestream. Before asking the user, check for it in:
   - The homepage (`index.md`) — announcement boxes often contain livestream links
   - The FTC page (`ftc.md`) — may have a championship info section with the link
   - Tournament info pages (`tournaments/ftc/*-Info.md`) — event logistics pages often embed the livestream
   - The scouting index (`scouting/index.md`) — may reference the video
   Only ask the user if the link can't be found on the site.
2. **FTC Events URL** — e.g., `https://ftc-events.firstinspires.org/2024/USARLCMP` — for scores, rankings, alliances, and awards
3. **Output filename** — the markdown file to create (e.g., `tournaments/ftc/2025-Adventist-Robotics-League-Championship-FTC.md`)

## Step-by-step process

### Step 1: Fetch scores and event data from FTC Events

**Option A — FTC API (preferred when credentials are available):**

Credentials are stored in `ftc-api-credentials.json` (git-ignored). To authenticate:

```python
import json, base64, urllib.request
with open('ftc-api-credentials.json') as f:
    creds = json.load(f)
token = base64.b64encode((creds['username'] + ':' + creds['auth_key']).encode()).decode()
headers = {'Authorization': 'Basic ' + token}
```

API base URL: `https://ftc-api.firstinspires.org/v2.0/{season}/`
- `matches/{event_code}` — all match results with teams and scores
- `scores/{event_code}/qual` — detailed score breakdowns per match
- `rankings/{event_code}` — rankings
- `teams?eventCode={event_code}` — team list
- `awards/{event_code}` — awards
- `alliances/{event_code}` — playoff alliance compositions

When using API data on pages, include an attribution link at the bottom: `<small>Match data provided by the [FIRST Tech Challenge Events API](https://ftc-events.firstinspires.org/services/API).</small>`

**Option B — Web scraping (fallback if no credentials):**

The FTC Events website at `https://ftc-events.firstinspires.org/{season}/{event_code}` provides the same data as HTML pages.

Fetch these pages using `web_fetch`:

1. **Teams**: `https://ftc-events.firstinspires.org/{season}/{event_code}` — team list with numbers, names, locations
2. **Qualifications**: `https://ftc-events.firstinspires.org/{season}/{event_code}/qualifications` — all qualification match results with red/blue alliance teams and scores
3. **Rankings**: `https://ftc-events.firstinspires.org/{season}/{event_code}/rankings` — qualification rankings (rank, team, ranking score, W-L-T, high score)
4. **Playoffs**: `https://ftc-events.firstinspires.org/{season}/{event_code}/playoffs` — playoff bracket results and alliance compositions
5. **Awards**: `https://ftc-events.firstinspires.org/{season}/{event_code}/awards` — all awards with team numbers and names

**Important**: The `{season}` in the URL refers to the FTC season code, not the calendar year. The 2024-25 season uses `2024`, the 2025-26 season uses `2025`, etc.

Parse the HTML/markdown output from `web_fetch` to extract:
- Qualification match data: match number, red alliance teams (2), blue alliance teams (2), red score, blue score, winner
- Rankings: rank, team number, team name, ranking score, W-L-T, high score
- Playoff matches: bracket position, red/blue alliances, scores, winner
- Alliance compositions: seed, captain team, pick teams
- Awards: award name, team number, team name

Individual match score breakdowns are available at:
- **Qualifications**: `https://ftc-events.firstinspires.org/{season}/{event_code}/qualifications/{match_number}`
- **Playoffs**: `https://ftc-events.firstinspires.org/{season}/{event_code}/playoff/{series}/{match_number}`

### Step 2 (Recommended): Find match timestamps using video frame capture

FTC tournament livestreams display a match overlay graphic at the bottom of the screen during matches. This overlay shows the match type and number (e.g., "Qualification 4 of 25"), team numbers for both alliances, and a countdown timer. Use Playwright to capture frames and read these overlays to find exact match timestamps.

This approach is more reliable than caption-based finding because it reads on-screen match data directly rather than relying on speech recognition.

#### Set up Playwright and open the video

```python
from playwright.sync_api import sync_playwright
import time

pw = sync_playwright().start()
browser = pw.chromium.launch(headless=True)
page = browser.new_page(viewport={"width": 1920, "height": 1080})
page.goto(VIDEO_URL, wait_until="domcontentloaded")
time.sleep(3)

# Dismiss consent dialogs
for text in ["Accept all", "Accept", "Reject all"]:
    try:
        page.locator(f'button:has-text("{text}")').click(timeout=2000)
        time.sleep(1)
        break
    except:
        pass

# Start playing to initialize the stream
try:
    page.click(".ytp-play-button", timeout=5000)
    time.sleep(3)
except:
    pass

# Check seekable range
seekable_end = page.evaluate("document.querySelector('video').seekable.end(0)")
```

#### Capture a frame at a specific timestamp

```python
def capture_frame(page, target_seconds, outfile):
    """Seek to target_seconds and screenshot the video element."""
    page.evaluate(f"document.querySelector('video').currentTime = {target_seconds}")
    time.sleep(3)  # wait for seek + buffer
    actual = page.evaluate("document.querySelector('video').currentTime")
    page.query_selector("video").screenshot(path=outfile)
    return actual
```

Seeking is accurate to within 2–3 seconds in the middle of the seekable range. Avoid seeking to the very start or very end of the range (stay at least 60 seconds from edges).

#### Scan the video for match timestamps

**Post-tournament analysis (all matches at once):** Scan forward through the video. Matches are sequential, so once you find match N, match N+1 is ~5–7 minutes later.

1. Estimate the first match position (~10–20 minutes in, after opening ceremonies)
2. Capture a frame. If no match overlay is visible, jump forward 2 minutes and retry.
3. When a match overlay appears, read the match number, team numbers, and timer
4. Verify team numbers against the FTC Events data for that match
5. Calculate the match start time (see below)
6. Estimate the next match position (~5–7 minutes later) and repeat
7. After all qualification matches, expect a 30–60 minute gap for alliance selection before playoffs

**Live tournament (finding a specific new match):** Search backward from the live edge.

1. The match just finished, so start from the current live position
2. Go back in 2-minute chunks, capturing a frame at each position
3. Look for the target match number in the overlay
4. When found, calculate the start time
5. YouTube live DVR typically covers ~6–14 hours, more than enough for a tournament day

#### Read the match overlay and calculate start time

Examine each captured frame for the FTC match overlay at the bottom ~15% of the screen:
- **Match identifier**: "QUALIFICATION 4 of 25" or "SEMIFINAL 1-1"
- **Team numbers**: 4 team numbers (2 red, 2 blue) — verify against FTC Events data
- **Timer**: remaining time in the current match period

**Calculate the match start time:**

FTC matches run: 30s autonomous → ~8s transition → 120s teleop ≈ 158s total.

| Timer shows | Period | Elapsed since match start |
|-------------|--------|--------------------------|
| 0:NN remaining in auto | Autonomous | `30 - NN` seconds |
| M:SS remaining in teleop | Teleop | `38 + (120 - teleop_remaining_seconds)` seconds |

**Match start time** = `frame_stream_position - elapsed_seconds`

Subtract ~5 seconds from the result to link to the pre-match countdown rather than the exact match start.

**Tips:**
- Look for frames where the timer is non-zero (match is actively running, not ended)
- If the overlay isn't visible, the video may be between matches, showing replays, or in a ceremony
- If you can't determine the period (auto vs teleop), capture another frame 30s earlier or later
- Each frame capture takes ~15 seconds (seek + buffer + screenshot)
- Verify team numbers in the overlay against FTC Events data to confirm you have the right match

If video frame capture is not feasible (e.g., video is private, Playwright not available, overlay not consistently visible), use the caption-based approach in Steps 3–5 below instead.

### Step 3 (Alternative): Get transcript from YouTube

**Option A — Auto-generated captions (try first):**

Use `yt-dlp` to download auto-generated English captions:

```bash
python -m yt_dlp --write-auto-sub --sub-lang en --sub-format vtt --skip-download -o "captions" "VIDEO_URL"
```

If that fails, try with the iOS player client:

```bash
python -m yt_dlp --extractor-args "youtube:player_client=ios" --write-auto-sub --sub-lang en --sub-format vtt --skip-download -o "captions" "VIDEO_URL"
```

**Option B — Whisper speech recognition (when captions are unavailable):**

Some livestreams have no auto-generated captions. In that case, download the audio and use Whisper:

```bash
# Download audio only
python -m yt_dlp -f 234 -o "tournament_audio.%(ext)s" "VIDEO_URL"

# Install faster-whisper
pip install faster-whisper
```

Then run speech recognition:

```python
from faster_whisper import WhisperModel
import json

model = WhisperModel("base", device="cpu", compute_type="int8")
segments, info = model.transcribe("tournament_audio.mp4", beam_size=5, language="en",
                                   vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500))

results = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
with open("transcript.json", "w") as f:
    json.dump(results, f, indent=2)
```

This takes ~8 minutes for a 3.5-hour video on CPU.

If yt-dlp is not installed or is outdated, install/update it:
```bash
pip install --upgrade yt-dlp
```

### Step 4 (Alternative): Parse transcript and find match timestamps

#### Step 3a: Parse captions into timestamped entries

Parse the VTT file into `(timestamp_seconds, text)` entries:
- Strip HTML tags
- Deduplicate consecutive identical text
- YouTube VTT captions have heavy duplication — the same text appears at multiple timestamps

#### Step 3b: Find all "three, two, one" countdowns

Search for ALL instances of countdown patterns in the captions:
- `three.{0,10}two.{0,10}one` (spoken words)
- `\b3.{0,5}2.{0,5}1\b` (digits)

Deduplicate within 8 seconds of each other.

#### Step 3c: Classify each countdown

**Critical insight: FTC matches have TWO "three, two, one" countdowns per match:**

1. **Match start (autonomous period)**: The announcer says "Let's start in three, two, one, go!" — this is the match start timestamp you want to record.

2. **Teleop start** (~30-40 seconds after match start): The announcer says "Drivers, pick up your controllers. Three, two, one." — this marks the transition from autonomous to driver-controlled period. **Do NOT record this as a match start.**

3. **Match end** (~150 seconds after match start): Sometimes captured as "Five, four, three, two, one" countdown. **Do NOT record this as a match start.**

Classification rules:

| Pattern in text | Classification |
| --- | --- |
| Contains "driver" AND ("controller" or "pick up") | **TELEOP START** — skip |
| Contains "five" or "5" BEFORE "three" or "3" | **MATCH END** — skip |
| Contains "let's start", "starting in", "get this started", "let's go in" | **MATCH START** — record |
| Contains "start" + "qualification" or "final" | **MATCH START** — record |
| Contains "we're ready" + "start" | **MATCH START** — record |
| Ambiguous — check if ~30s after a known match start | Likely **TELEOP** — skip |
| Ambiguous — check context for game commentary ("climb", "bucket", "score") | Likely **MATCH END** — skip |

#### Step 3d: Validate match starts

For each classified MATCH START, look for a corresponding TELEOP START 25-45 seconds later:
- If found → **validated match start** (high confidence)
- If not found → still likely a match start (captions miss ~30-40% of teleop countdowns)

The total match start count should equal: qualification matches + playoff matches (e.g., 25 + 7 = 32 for a typical 20-team tournament).

#### Step 3e: Map timestamps to matches

Map the validated match starts to the qualification and playoff matches in sequential order:
1. First N timestamps → Qualification 1 through Qualification N
2. After a significant gap (typically 30-60 minutes for alliance selection) → Playoff matches in order

Watch for a **lunch break** between qualification matches (typically a 60-90 minute gap in timestamps). The matches continue in sequence after the break.

### Step 5 (Alternative): Verify match-to-timestamp mapping

Search the captions near each match start for team numbers and names to verify the mapping:
- Look within 2 minutes before each countdown for team number mentions
- The announcer typically introduces teams before each match: "On our red alliance, we have team 18783 Eagle Tech..."
- Team numbers are more reliable than names in auto-captions (names are often misheard)

Also search for explicit match number mentions:
- "qualification 4", "qualification match 10", "match 25"
- These confirm the mapping when found

**If there are extra or missing countdowns:**
- Extra: Check for false starts ("reset", "stop" within 30s after countdown), opening ceremony kickoffs, or match redos
- Missing: Estimate timestamps based on spacing between known matches (FTC matches are typically 5-7 minutes apart)

**If the FTC API has scheduled match times**, you can compute a time offset between the API's scheduled times and your caption timestamps. If the offset is consistent across known matches, apply it to calculate timestamps for missing ones. This works well when the schedule ran on time but may be unreliable if there were significant delays.

#### Using frame capture to fill gaps (hybrid approach)

When caption-based timestamps have gaps or ambiguous spots — for example, matches with irregular spacing, unclear countdown classifications, or large sections without usable captions — use Playwright frame capture (Step 2) to resolve them. This is faster than scanning the entire video with frames, and more reliable than interpolation when the match schedule wasn't regular.

1. Identify the gaps: time ranges where you expect a match start but have no confident caption timestamp
2. For each gap, capture 2–3 frames at estimated positions within the gap
3. Read the match overlay to confirm which match is playing and calculate the exact start time
4. This typically requires only 5–10 frame captures total (~2 minutes), not one per match

### Step 6: Search for awards ceremony timestamps

Search the last ~30-60 minutes of captions for award announcements. Standard FTC awards (in typical order of announcement):

1. **Leadership Award** — individual student award
2. **Design Award** — mechanical and programming design
3. **Motivate Award** — spreading the culture of FIRST
4. **Control Award** — autonomous/sensor innovation
5. **Innovate Award** (sponsored by RTX) — most inventive team
6. **Connect Award** — community and industry connections
7. **Think Award** — engineering portfolio and process
8. **Finalist Alliance** — second-place playoff alliance
9. **Winning Alliance** — first-place playoff alliance
10. **Inspire Award** (1st, 2nd, 3rd) — best overall team

The number of runner-ups for each award varies based on tournament size and judge discretion — some awards may have no runner-up, one runner-up, or multiple. The Inspire Award typically has 3 places but may have fewer at smaller events. Don't assume a fixed number; use what the captions show.

Search for keywords: "award", "inspire", "think award", "connect", "innovate", "control award", "motivate", "design award", "winning alliance", "finalist alliance", "winner", "runner up"

Record the timestamp for each award announcement.

For each award, extract from the captions:
1. **Award description** — the announcer reads a standard description of what each award recognizes. Clean up the auto-caption text into proper English (fix stutters, grammar, capitalize "FIRST" properly).
2. **Judges' citation** — the announcer reads what the judges wrote about the team *before* announcing the winner (the audience hears the citation first, then the team name). Extract this and clean it up. These are typically 2-4 sentences starting with phrases like "Here's what the judges had to say..." or "This team..."
3. **Runner-up citations** — some awards have runner-ups with their own citations. Extract citations for each if available.

Format award descriptions as italicized text and judges' citations as blockquotes (see template below).

### Step 7: Generate the markdown page

Use the collected data to create the markdown file following this template:

```markdown
---
layout: page
title: "TOURNAMENT_NAME — FTC"
---

# TOURNAMENT_NAME — FTC

**DATE · LOCATION · SEASON_NAME Season**

On this page you can see the results of the TOURNAMENT_NAME FTC tournament. There are links to the start of each match in the livestream video. This is great for sharing with friends and family who weren't able to attend the tournament, so they can see the excitement and hard work on display. You can also use it to review your matches and look for ways to improve, or scout strategies that other teams are using!

**Tip:** Click on any team number to highlight all of that team's appearances on the page.

[Full tournament livestream](VIDEO_URL)

[Event results on FTC Events](EVENT_URL)

## Qualification Matches

| Match | Red Alliance 1 | Red Alliance 2 | Red Score | Blue Alliance 1 | Blue Alliance 2 | Blue Score | Video Link |
| ----- | -------------- | -------------- | --------- | --------------- | --------------- | ---------- | ---------- |
| Q1 | TEAM_NUM TEAM_NAME | TEAM_NUM TEAM_NAME | **SCORE** | TEAM_NUM TEAM_NAME | TEAM_NUM TEAM_NAME | SCORE | [TIMESTAMP](VIDEO_URL&t=SECONDS) |

Bold the winning score.

## Qualification Rankings

| Rank | Team | Ranking Score | W-L-T | High Score | OPR |
| ---- | ---- | ------------- | ----- | ---------- | --- |
| 1 | TEAM_NUM TEAM_NAME | RS | W-L-T | HIGH | OPR |

Calculate OPR from qualification matches using no-penalty scores. **Important:** `scoreRedFoul` = fouls committed BY red (added to blue's score). To get no-penalty red score, subtract `scoreBlueFoul` (opponent's committed fouls) from `scoreRedFinal`, NOT `scoreRedFoul`. See the scouting processor skill for the full OPR calculation method. Round to whole numbers.

## Playoff Matches

Alliances were formed through alliance selection after qualification matches. The top-ranked teams selected their alliance partners for a double-elimination playoff bracket.

### Alliances

| Seed | Captain | Pick |
| ---- | ------- | ---- |
| 1 | TEAM_NUM TEAM_NAME | TEAM_NUM TEAM_NAME |

### Bracket

| Match | Red Alliance | Blue Alliance | Red Score | Blue Score | Video Link |
| ----- | ------------ | ------------- | --------- | ---------- | ---------- |
| BRACKET_POSITION — Match N | TEAM / TEAM | TEAM / TEAM | **SCORE** | SCORE | [TIMESTAMP](VIDEO_URL&t=SECONDS) |

## Awards Ceremony

[Start of awards ceremony](VIDEO_URL&t=SECONDS)

### AWARD_NAME — [TIMESTAMP](VIDEO_URL&t=SECONDS)

*Award description read by the announcer, cleaned up from captions into proper English.*

- Runner-up: TEAM_NUM TEAM_NAME
- **Winner: TEAM_NUM TEAM_NAME**

> "Judges' citation for the winner, extracted from the captions and cleaned up."

<small>Match data provided by the [FIRST Tech Challenge Events API](https://ftc-events.firstinspires.org/services/API). This page was generated with the help of the [FTC Tournament Analyzer](https://github.com/wccarobotics/wccarobotics.github.io/blob/main/.claude/skills/ftc-tournament-analyzer/SKILL.md) AI skill.</small>
```

Video links use the format: `https://www.youtube.com/watch?v=VIDEO_ID&t=SECONDS`

**Team highlighting**: The site includes `assets/js/team-highlight.js` which automatically makes team numbers clickable on tournament pages. When a user clicks a team number, all occurrences of that team are highlighted in orange across the entire page (with table cells getting a background wash). No special markup is needed — the script detects team numbers (4-5 digit numbers followed by a name) in table cells and list items, including inside links.

### Step 8: Add to FTC tournaments index

After creating the tournament page, add an entry to `tournaments/ftc/index.md`. Follow the existing card format:

```html
<div class="tournament-card">
  <h3><a href="/tournaments/ftc/FILENAME">TOURNAMENT_NAME</a></h3>
  <p><strong>DATE</strong> · N teams · LOCATION</p>
  <p>🏆 Inspire Award: TEAM_NAME · Winning Alliance: TEAM_NAME / TEAM_NAME</p>
  <a href="/tournaments/ftc/FILENAME" class="btn btn-blue" style="margin-top: 0.5rem;">View Results →</a>
</div>
```

### Step 9: Clean up

Remove temporary files: `captions.en.vtt`, `transcript.json`, `tournament_audio.mp4`, and any Python scripts created during the process.

## Key technical details

### FTC match structure
- Each FTC match has **two alliances** (red and blue), each with **2 teams** (4 robots total on the field)
- Matches are **2.5 minutes** long: **30 seconds autonomous** + **2 minutes teleop** (driver-controlled)
- This means **two "3-2-1" countdowns per match**: one for autonomous start, one for teleop start (~30-40s later)
- Qualification matches: Teams are randomly assigned to alliances. Each team plays 5 qualification matches.
- Playoff matches: Top teams select alliance partners. Playoffs use a **double-elimination bracket** (upper/lower bracket format).
- Unlike FLL, FTC is **competitive** (alliance vs alliance) not independent scoring

### FTC countdown patterns
- **Match start (autonomous)**: The announcer says "Referees, are we ready? Scorekeeper, are we ready? All right, let's start in three, two, one, go." Variations include "let's go in three two one", "we're starting in three two one", "get this started in three two one"
- **Teleop start** (~30-40s after match start): "Drivers, pick up your controllers. Three, two, one." This is always preceded by "autonomous" or "auto" ending
- **Match end**: "Five, four, three, two, one" or "5, 4, 3, 2, 1" — counting down the final seconds

### Distinguishing FTC from FLL countdowns
| Feature | FLL | FTC |
| --- | --- | --- |
| Countdown word | "three two one LEGO" | "three two one go" |
| Second countdown | None | "Drivers, pick up controllers. 3 2 1" |
| Match length | ~150s (2.5 min) | ~150s (30s auto + 120s teleop) |
| Team structure | 2 independent teams per table | 2 alliances of 2 teams (4 robots) |
| Scoring | Independent per team | Alliance vs alliance (competitive) |

### FTC Events website data format
The FTC Events website returns reasonably structured HTML that `web_fetch` converts to readable markdown. Key patterns:

**Qualification matches page**: Each match shows:
- Match number and date/time
- Red alliance: 2 team numbers and names
- Blue alliance: 2 team numbers and names
- Red score and blue score (winning score is **bold**)

**Rankings page**: Table with Rank, Team (number + name), RS (Ranking Score), AUTO, ASCENT, High Score, W-L-T, Plays

**Playoffs page**: Shows bracket matches with round/position info (Upper Bracket Round 1, Lower Bracket Round 2, Finals, etc.) plus alliance compositions

**Awards page**: Table with Award Name, Team Number, Winner/Team Name

### FTC season naming
- The season code in URLs uses the starting year: `2024` = 2024-25 season, `2025` = 2025-26 season
- 2024-25 season: "INTO THE DEEP" (specimens and samples)
- 2025-26 season: "DECODE" (artifacts)

### Common issues
- Auto-generated captions miss ~30-40% of teleop countdowns, but match start countdowns are more reliably captured
- Team names are often misheard in captions (e.g., "War Eagle Tech" instead of "Eagle Tech", "Wing Nuts" split into two words, "CPU Sers" instead of "CPUsaders")
- Team numbers are more reliable than names — search for digit sequences
- Some tournaments have a very long lunch break (60-90 minutes) between qualification match blocks — don't let the gap confuse round grouping (qualifications are all one continuous sequence, not multiple rounds like FLL)
- The announcer may mention "qualification X" numbers but not consistently — use sequential mapping as the primary approach
- Opening ceremonies or pre-match speeches may contain "three two one" but lack the "let's start" or "referees are we ready" context
- Match redos are rare in FTC but can happen — look for extra countdowns in unexpected positions
- FTC API credentials are stored in `ftc-api-credentials.json` (git-ignored). If credentials are missing, fall back to web scraping `ftc-events.firstinspires.org`
- Awards ceremony order may vary between events — use the captions to determine the actual order rather than assuming a fixed order
- Some events may have additional awards beyond the standard set (e.g., Leadership Award, Judges Award)

### Verification checklist
After generating the page, verify:
1. Total qualification match count matches the events page
2. Total playoff match count matches the events page
3. Scores on the page match the FTC Events data exactly
4. Each team appears the correct number of times in qualifications (typically 5 matches per team)
5. Playoff alliance compositions are consistent across all playoff matches
6. Awards match the FTC Events awards page
7. Video timestamps link to the correct moments (spot-check a few by clicking)
8. All match start timestamps are ~5-7 minutes apart (typical FTC match spacing)

## Dependencies

```bash
pip install yt-dlp
```

For videos without auto-generated captions:
```bash
pip install faster-whisper
```

For optional video frame capture (to read on-screen graphics for match/team validation):
```bash
pip install playwright
python -m playwright install chromium
```
