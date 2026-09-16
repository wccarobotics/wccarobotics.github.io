---
name: fll-tournament-analyzer
description: Analyze an FLL tournament livestream video to find match timestamps, fetch scores from FLL Gameday, and generate a markdown page documenting all matches, rankings, and awards. Use this skill when asked to create a tournament summary page from an FLL livestream video.
---

# FLL Tournament Analyzer

This skill analyzes an FLL (FIRST LEGO League) tournament livestream video to produce a markdown page documenting every match with timestamped video links, scores, rankings, and awards — following the format used in [Florida-Qualifier.md](https://github.com/wccarobotics/submerged/blob/main/Florida-Qualifier.md).

## When to use this skill

- When the user provides an FLL tournament livestream URL and asks to document it
- When the user wants match timestamps extracted from an FLL video
- When creating a tournament summary markdown page

## Required inputs

1. **YouTube video URL** — the full tournament livestream (there may also be a separate awards ceremony video)
2. **Output filename** — the markdown file to create (e.g., `Carolina-Qualifier.md`)

One of the following for scores (in order of preference):
3. **FLL Gameday scoreboard URL** — e.g., `https://fllgameday.com/scoreboard/{event-id}` (best: structured data via API)
4. **Scoreboard visible in video** — if no API link, use Playwright to screenshot the YouTube player at the timestamp where the scoreboard is shown, then read scores from the image

Highly recommended:
- **Schedule PDF/image** — provides the correct **match pairings and match order**. This is the most reliable source for knowing which teams play together and in what sequence. Schedule *times* are NOT useful — tournaments rarely run on schedule.

Optional:
- **Example format** — defaults to the Carolina-Qualifier.md / Mid-Atlantic-Qualifier.md format

## Step-by-step process

### Step 1: Fetch scores

**Option A — FLL Gameday API (preferred when a scoreboard URL is available):**

The FLL Gameday scoreboard is a Vue.js SPA. The data is available via a REST API:

```
GET https://api.fllgameday.com/public/scoreboard/{event-id}
GET https://api.fllgameday.com/public/event/{event-id}
```

Extract the `{event-id}` from the scoreboard URL (it's the UUID at the end).

The scoreboard API returns a JSON array with each team's data:
```json
{
  "customTeamId": "54580",
  "rank": 1,
  "name": "Gear Girls",
  "practice": 320,
  "match1": 335,
  "match2": 360,
  "match3": 395,
  "highScore": 395
}
```

Use `web_fetch` to retrieve this data. Store the team list and all scores.

**Option B — Screenshot scoreboard from video (when no API link is available):**

If there's no FLL Gameday link, the scoreboard is often shown on-screen during the livestream. Use Playwright to screenshot the YouTube player at the relevant timestamp:

```python
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(f"https://www.youtube.com/watch?v={VIDEO_ID}&t={TIMESTAMP_SECONDS}", wait_until="networkidle", timeout=60000)
    time.sleep(5)
    try:
        page.click('button[aria-label="Accept all"]', timeout=3000)
    except:
        pass
    try:
        page.click('.ytp-play-button', timeout=3000)
        time.sleep(3)
        page.click('.ytp-play-button', timeout=3000)  # pause
    except:
        pass
    video_el = page.query_selector('video')
    if video_el:
        video_el.screenshot(path="scoreboard_video.png")
    browser.close()
```

Install Playwright if needed: `pip install playwright && python -m playwright install chromium`

Read the scores from the screenshot image. The scoreboard typically shows: Rank, Team Number, Team Name, High Score, Match 1, Match 2, Match 3, Practice.

### Step 2: Get transcript from YouTube

**Option A — Auto-generated captions (try first):**

Use `yt-dlp` to download auto-generated English captions. **Important:** The standard `--write-auto-sub --skip-download` approach often fails with "Did not get any data blocks" due to YouTube signature extraction issues. Use this workaround:

```bash
yt-dlp --extractor-args "youtube:player_client=ios" --write-auto-sub --sub-lang en --sub-format vtt --skip-download -o "captions" "VIDEO_URL"
```

The `youtube:player_client=ios` flag bypasses the signature extraction problem.

**Option B — Whisper speech recognition (when captions are unavailable):**

Some livestreams have no auto-generated captions. In that case, download the audio and use Whisper:

```bash
# Download audio only
yt-dlp --extractor-args "youtube:player_client=ios" -f 234 -o "tournament_audio.%(ext)s" "VIDEO_URL"

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

This takes ~8 minutes for a 3.5-hour video on CPU. The output is a JSON array of `{start, end, text}` segments. Note: Whisper transcription may have gaps during music/silence and team names are often misheard worse than YouTube auto-captions.

If yt-dlp is not installed or is outdated, install/update it:
```bash
pip install --upgrade yt-dlp
```

### Step 3: Parse transcript and find match timestamps

The most reliable workflow for finding match timestamps uses the **schedule for pairings/order** and **captions for timestamps**:

#### Step 3a: Parse the schedule for pairings and match order

If a schedule PDF/image is provided, extract the match pairings for each round. The schedule tells you:
- **Which teams play together** (pairings) — this is the primary source of truth
- **Match order** — which pair runs first, second, etc.
- **Table/pod structure** — how many tables run per time slot

**Important:** Schedule *times* (e.g., "1:20 PM", "1:28 PM") are NOT useful for finding matches in the video. Tournaments rarely run on schedule. Use the times only to understand the intended ORDER of matches.

Cross-reference the schedule with the API data:
- **Teams on the schedule but missing from the API** = dropped before registration (removed from event entirely)
- **Teams in the API with null scores** = registered but didn't attend
- Both create solo matches — the absent team's partner runs alone

#### Step 3b: Find match start countdowns in captions

Run the analysis script to find countdown markers:

```bash
python .claude/skills/fll-tournament-analyzer/analyze_tournament.py \
  --captions captions.en.vtt \
  --scoreboard-id {event-id} \
  --output analysis.json
```

The script finds start countdowns ("3-2-1 LEGO") and end countdowns ("10-9-8...1 stop"). **Use the script primarily for countdown detection** — its round grouping and team pairing from captions are unreliable when a schedule is available.

Also verify countdowns manually by pairing starts with ends:
- A valid match has a START → END pair ~140-160 seconds apart
- Unpaired starts (no end within range) may be false detections or the opening ceremony kickoff
- Unpaired ends may indicate a missed start countdown

**Beware the ceremonial "321 LEGO"**: The opening ceremony often ends with a crowd countdown ("321 LEGO!") to kick off the competition. This is NOT a match start — it has no corresponding end countdown ~150s later. Exclude it.

#### Step 3c: Map countdowns to schedule matches with AI verification

**Key insight: Tables/pods typically run sequentially, not simultaneously.** Even when the schedule lists multiple pods at the same "time" (e.g., "1:20 PM — Pod 1 and Pod 2"), each pod gets its own separate countdown 3-5 minutes apart. So:

- A tournament with 2 pods and 5 time slots per round has **10 countdowns per round** (not 5)
- Countdowns naturally pair up: Pod 1 start, Pod 2 start (3-5 min later), then gap to next time slot

**⚠️ DANGER: Sequential assignment is fragile.** If you blindly map "the Nth detected countdown → the Nth scheduled match," a single missed countdown shifts EVERY subsequent match to the wrong timestamp. This commonly happens because:
- Surrogate match countdowns are sometimes muffled, mistimed, or the announcer skips the formal "3-2-1 lego" ("we're just going to start this practice run").
- Auto-captions occasionally drop a countdown entirely.
- The number of detected countdowns rarely matches the number of scheduled matches exactly.

**The correct approach: AI-assisted whole-transcript mapping.** Don't rely on regex/keyword matching alone for team identification. Instead, after dedup and parsing the transcript:

1. Split the focus window of the transcript (from first match to last match) into a clean text file with `[H:MM:SS t=SECONDS] caption` per line.
2. Launch a sub-agent (e.g., Claude Sonnet) with:
   - The full transcript text file (typically 100-300KB)
   - The complete team list (number → name)
   - The schedule pairings in announced order, including surrogate slot positions (start vs end of round)
   - Common auto-caption mishearings to expect (see below)
3. Ask the sub-agent to identify EVERY match start countdown AND identify the two teams playing using announcer callouts in the ~30-90 seconds **before** the countdown ("team 54580…it's team 69511…3, 2, 1, Lego!").
4. The sub-agent should produce one row per match: `t=, HH:MM:SS, Round, Teams, Surrogate?, Evidence (caption snippets)`.

This is dramatically more reliable than script-based mapping because the AI:
- Reads team names AND numbers in context (handles "five-four-five-eight-zero" digit-by-digit callouts).
- Handles common mishearings ("Speed Coders" → "Code Breakers"/"coat breakers", "Marcus Bartholomew" → "Marcus Baral", "TerraBots" → "Terabucks", "EnginEagles" → "Indian Eagles").
- Detects surrogate matches via explicit announcer language ("stepping in as a surrogate", "we have a blank spot", "practice round").
- Can distinguish match countdowns from the opening ceremony "3-2-1 lego" kickoff.

#### Step 3d: Verify EVERY mapping before generating the page

**This is the step that was missing the first time and caused massive errors.** After producing a mapping, validate it before writing markdown:

1. **For each match, check that the announcer named both assigned teams** in the ~60 seconds before the countdown. If a caption near the countdown names different teams, the mapping is wrong.
2. **Cross-check sequential timestamps** — countdowns within the same time slot should be 3-5 minutes apart; between slots there's typically a 4-8 minute gap; between rounds there's often a 10+ minute gap. A "match" with a 0-minute gap from the previous one is suspicious.
3. **Watch for cascading errors** — if you find one wrong assignment, check ALL surrounding matches. A single off-by-one error from a missed surrogate countdown tends to shift many matches.
4. **Don't invent "exhibition matches"** — if there are extra timestamps that don't fit your mapping, your mapping is more likely wrong than there being unscheduled matches. Verify before adding exhibition match notes.

#### Step 3e: Identify each surrogate volunteer

Each round with an odd team count has one surrogate match where a volunteer team plays alongside the team whose schedule slot has `*` or is blank. **Identify each volunteer explicitly from captions** — do not guess. Search the transcript for:
- "surrogate"
- "stepping in"
- "volunteer"
- "blank spot"
- "practice run" / "practice round" (sometimes used)

The announcer typically thanks the volunteer team by name shortly after they play. Example: *"I want to give kudos to Iron Eagles because they're stepping in as a surrogate team."*

If you have Whisper JSON output instead of VTT, analyze it directly. Search the transcript for:

1. **Match start markers** — countdown patterns: "three, two, one", "3, 2, 1", followed by "lego", "go", "start"
2. **Team identification** — search for team numbers and team names within a 2-minute window before each countdown
3. **Round boundaries** — 5-15 minute gaps between rounds, often with breaks, interviews, or games

The script / manual analysis should:
1. Parse captions/transcript into timestamped text entries
2. Search for match start markers (countdown patterns) and match end markers
3. Pair starts with ends (~140-160s apart) to confirm valid matches
4. **Use the schedule** to determine match pairings and order (don't rely on caption-based team identification)
5. Map confirmed countdowns to scheduled matches in sequential order (accounting for sequential pod/table execution)
6. Verify structural consistency (each team once per round, countdown counts match, START-END pairs valid)
7. Output structured match data

### Step 4: Review and refine

The auto-generated captions are imperfect. After the script runs, **manually review** the output:

1. **Verify team pairings** — Check that each team appears exactly once per round. If a pairing seems wrong, search the captions near that timestamp for clues. **When a schedule is available, trust it over caption-based team identification.**
2. **Pair START with END countdowns** — Each valid match should have a START countdown ("3-2-1 LEGO") followed by an END countdown ("10-9-8...1 stop") ~140-160 seconds later. Unpaired starts may be the opening ceremony kickoff, false starts, or exhibition runs.
3. **Check for special events** — Look for match redos (clock malfunctions), false starts ("reset", "stop" after countdown), solo matches (odd team count or absent teams), and exhibition runs after official matches.
4. **Verify round boundaries** — There's typically a 5-10 minute gap between rounds, but some tournaments have very short gaps. Use "end of round X" announcements and team pairings to determine boundaries, not just timing gaps. The announcer may start a new round before announcing the previous round's scores.
5. **Verify countdown count** — Count the total detected start countdowns and compare to expected matches. With N pods running sequentially per time slot, each round has N × time_slots countdowns. Extra countdowns may be false starts, exhibition runs, or the opening ceremony. Missing countdowns (~5 of 30 may be missed by auto-captions) need estimated timestamps.
6. **Awards ceremony** — Search the last ~30-60 minutes of captions for award announcements. **If the video ends without any awards content**, the awards are likely in a separate video — ask the user. Look for keywords: "award", "finalist", "winner", "champion", "core values", "innovation", "robot design", "robot performance", "advancing".

### Step 5: Generate the markdown page

Use the analysis JSON to create the markdown file following this format:

```markdown
# Tournament Name

On this page you can see the results of the TOURNAMENT_NAME. There are links to the start of each match in the livestream video. This is great for sharing with friends and family who weren't able to attend the tournament, so they can see the excitement and hard work on display. You can also use it to review your matches and look for ways to improve, or scout strategies that other teams are using!

**Tip:** Click on any team number to highlight all of that team's appearances on the page.

[Full tournament livestream](VIDEO_URL)

[Robot game scoreboard](SCOREBOARD_URL)

## Round 1

| Team A | Points Scored | Team B | Points Scored | Video Link |
| ------ | ------------- | -------| ------------- | ---------- |
| TEAM_NUM TEAM_NAME | SCORE | TEAM_NUM TEAM_NAME | SCORE | [TIMESTAMP](VIDEO_LINK?t=SECONDS) |

For odd-team tournaments with surrogates:
| TEAM_NUM TEAM_NAME | SCORE | TEAM_NUM TEAM_NAME *(surrogate)* | — | [TIMESTAMP](VIDEO_LINK?t=SECONDS) |

For odd-team tournaments with solo runs (no partner):
| TEAM_NUM TEAM_NAME | SCORE | — | — | [TIMESTAMP](VIDEO_LINK?t=SECONDS) |

*Note: Exhibition/bonus runs after all official matches should NOT be in the match table. Add a footnote:*
> *TEAM_NUM TEAM_NAME had an [exhibition run](VIDEO_LINK?t=SECONDS) after all official matches.*

## Round 2
...

## Round 3
...

## Robot Game Rankings

| Rank | Team | High Score | Match 1 | Match 2 | Match 3 |
| ---- | ---- | ---------- | ------- | ------- | ------- |
| 1 | TEAM_NUM TEAM_NAME | HIGH | M1 | M2 | M3 |

## Awards Ceremony

- Start of awards ceremony [TIMESTAMP](VIDEO_LINK?t=SECONDS)
- Participation medals
  - [TEAM_NUM TEAM_NAME](VIDEO_LINK?t=SECONDS)
- Awards
  - [Award Name](VIDEO_LINK?t=SECONDS)
    - Finalist: TEAM_NUM TEAM_NAME *(if applicable)*
    - Finalist: TEAM_NUM TEAM_NAME *(if applicable)*
    - Winner: TEAM_NUM TEAM_NAME
```

Video links use the format: `https://www.youtube.com/live/VIDEO_ID?t=SECONDS`

**Team highlighting**: The site includes `assets/js/team-highlight.js` which automatically makes team numbers clickable on tournament pages. When a user clicks a team number, all occurrences of that team are highlighted in orange across the entire page (with table cells getting a background wash). No special markup is needed — the script detects team numbers (4-5 digit numbers followed by a name) in table cells and list items, including inside links.

### Step 6: Add to tournaments index

After creating the tournament page, add an entry to `tournaments/fll/index.md`. Follow the existing card format, grouping by season. Each card includes a one-line results summary that **must include the Champions Award winner** (the most important award), plus the Robot Performance (high-score) winner. Example:

```html
<div class="tournament-card">
  <h3><a href="/tournaments/fll/FILENAME">Tournament Name</a></h3>
  <p><strong>Month Day, Year</strong> · N teams · Venue</p>
  <p>🏆 Champions Award: TEAM_NAME · Robot Performance: TEAM_NAME (HIGH pts)</p>
  <a href="/tournaments/fll/FILENAME" class="btn btn-blue" style="margin-top: 0.5rem;">View Results →</a>
</div>
```

If the tournament has a special event with its own champion (e.g., an Alliance Games bracket), add it to the summary too, but still include the Champions Award: `🏆 Champions Award: X · Alliance Champions: Y · Robot Performance: Z (pts)`.

### Step 7: Clean up

**⚠️ Do NOT clean up working files until the user explicitly confirms they are happy with the finished results page.** Users frequently spot-check timestamps and request corrections after the first draft (e.g., "this match link is a few seconds early," "find the two missing matches"). Each correction usually requires the downloaded audio/video, the transcript JSON, and the transcribe script. If you delete these prematurely, you have to re-download and re-transcribe from scratch — which is slow and wasteful and happened repeatedly before this rule existed. Keep `tournament_audio.mp4`, any windowed clips, the transcript JSON(s), `tx.py`/transcribe scripts, and verification frames in a working directory until the user signs off.

Once the user confirms the page is final, remove temporary files: `captions.en.vtt`, `analysis.json`, `transcript.json`, `tournament_audio.mp4`, windowed `*.mp4` clips, verification frames, `scoreboard_video.png`, and any Python scripts created during the process.

## Key technical details

### FLL match structure
- Each FLL tournament has **3 qualifying rounds** (plus an optional practice round)
- Each round has every team playing exactly once
- Two teams run on the same table simultaneously (they get independent scores, not versus each other)
- **Table configurations vary widely**: Tournaments may have 1, 2, 3, or more tables. **Tables almost always run sequentially** — even when the schedule lists multiple tables at the same time slot, each table gets its own countdown 3-5 minutes apart. Each time slot therefore produces N countdowns (one per table). Don't assume tables start simultaneously. Listen for table names/colors (e.g., "red table", "blue table", "pod 1", "pod 2") in the announcer's commentary.
- Each match is **2.5 minutes** (~150 seconds) long
- **Odd number of teams**: When there's an odd number of teams, each round has one team without a partner. This is handled in one of two ways:
  - **Surrogate match**: A volunteer team fills the empty table slot. The surrogate's score does NOT count in rankings. Mark with *(surrogate)* and use `—` for the score. Three surrogate teams are selected at the coaches meeting (one per round).
  - **Solo match**: The odd team runs alone with no partner. Their score still counts. Mark the missing partner with `— | —` in the table. The solo match may be at its scheduled position or moved to the end of the round.
- **Even number of teams**: No surrogates needed; all matches are scored
- **Cross-round matches**: Some schedules have a match where one physical run counts as Round 1 for one team and Round 2 for the other. This means one round has one fewer physical match (that team already got their score from the cross-round). Note these with a footnote explaining which team gets which round's score.
- **Exhibition/bonus matches**: After all official rounds complete, a team may get an extra unofficial run (e.g., the announcer says "finish one more match"). These don't count for scoring — the team already has all 3 round scores. Note these separately from official matches.

### Caption/transcript analysis heuristics
- **Match start markers**: "three, two, one" or "3, 2, 1" followed by "lego", "let's go", "let go", "go", or "start". Auto-captions often mishear "lego" as "let go."
- **Match end markers**: "five, four, three, two, one" (or "10, 9, 8...") followed by "stop", "time's up". The key distinction: END countdowns count DOWN TO STOP from 5 or 10, while START countdowns count "three, two, one" then say "lego"/"let go."
- **Distinguishing START from END countdowns**: Both contain "three, two, one." To tell them apart: (1) if "five, four" or "10, 9, 8" appears BEFORE the "three, two, one," it's an END countdown; (2) if "lego" or "let go" appears AFTER, it's a START; (3) verify by checking that START-END pairs are ~140-160 seconds apart.
- **False starts / restarts**: Sometimes a match is started but immediately stopped ("reset that", "stop guys", "sorry", "restart"). A new countdown follows. Exclude the false start timestamp — use the restart. Look for "reset", "stop", "sorry", "restart", "again" within 30 seconds after a countdown.
- **Announcer announces NEXT match while CURRENT match runs**: Team names mentioned near a countdown may be for the upcoming match being called to the table, not the match currently starting. The announcer often calls "Team X and Team Y, come to the red table" while the blue table match is still running. Use the schedule pairings as the primary source of truth for which teams play when.
- **Team identification**: Search for team numbers (e.g., "36689") and team names (e.g., "mission possible", "gear girls") within 2 minutes before a countdown. Team numbers spoken digit-by-digit (e.g., "five, nine, six, zero, two") are common in auto-generated captions and Whisper output. **Always fetch the scoreboard API first** to get accurate team names, then search captions for those exact names.
- **Round gaps**: Typically 5-15 minutes between the last match of one round and the first of the next. Gaps often include interviews, emoji games, or break announcements. However, some tournaments have very short gaps (~60 seconds) between rounds if teams are already queued.
- **VTT deduplication**: YouTube VTT captions have heavy duplication — the same text appears at multiple timestamps as the caption updates. Deduplicate entries by `(int(start_seconds), text)` key before analysis.
- **Awards section**: Usually in the last 20-60 minutes of the video, **but may be in a completely separate video/livestream**. The main livestream sometimes ends before the awards ceremony (e.g., during judges' deliberation). Ask the user if there's a separate awards video. Search for: "award", "champion", "core values", "innovation", "robot design", "robot performance", "advancing". The number of finalists depends on tournament size — **smaller tournaments may only announce a winner** with no finalists, while **larger tournaments may have one or two finalists** before the winner. Search for "finalist" mentions before "winner" but don't assume they exist.
- **Whisper VAD gaps**: When using Whisper with VAD filtering, segments of music or ambient noise will be skipped entirely. The awards ceremony often has long music gaps where award names may be lost — flag these for the user to fill in manually.

### Common issues
- Auto-generated captions and Whisper both often mishear team names (e.g., "Mission Impossible" instead of "Mission Possible", "Cicero Circus" instead of "Cicero Circuit", "table bots" or "tail bots" instead of "TerraBots", "harbots" instead of "Hobbots", "Shark Novas" instead of "Sharknovus", "Aquinauts" instead of "Aquanauts")
- Team numbers are more reliable than names — search for both digit sequences ("69648") and spoken digits ("six, nine, six, four, eight")
- Some matches may have no team names in nearby captions — use process of elimination
- Not all match starts have a clear countdown — the announcer may just say "let's start" or "lego" without a formal 3-2-1. Search for "start this match" and "lego" as additional markers.
- Clock malfunctions can cause match redos, creating extra countdowns. Also look for false starts where the announcer says "reset" or "stop" immediately after a countdown.
- **Opening ceremony "321 LEGO" is NOT a match**: The opening ceremony often ends with a crowd countdown ("Everyone, let's do a 321 LEGO!") to kick off the competition. This will be detected as a match start but has no corresponding end countdown ~150s later. Verify all detected starts have matching ends before counting them as matches.
- Practice rounds may or may not be in the video depending on when the livestream started
- The schedule image/PDF (if provided) may list teams that were later removed. **Always cross-reference the schedule with the API team list.** Teams on the schedule but absent from the API dropped before the event. Teams in the API with null scores registered but didn't attend. Both create solo matches for their scheduled partners.
- **Schedule times are unreliable** — tournaments rarely start on time and often fall behind schedule. A match scheduled for "1:44 PM" might actually happen 10+ minutes late. Use the schedule only for pairings and order, never for video timestamp estimation.
- Surrogate teams sometimes decline to play (as seen in Mid-Atlantic tournament), requiring another team to volunteer. Listen for "surrogate" mentions. Some tournaments skip surrogates entirely and let the odd team run solo instead.
- The announcer may be confused about round numbering (e.g., calling the "second competition round" the "third set of rounds"). Use match timestamps and team pairings to determine the actual round structure, not the announcer's numbering.
- **"Unknown creature", "shark", "coral"** — these are game element names from the SUBMERGED season, NOT team names. Don't confuse in-game commentary ("we got the shark released") with team identification ("Sharknovus is at the blue table").
- **Awards ceremony gaps**: When using Whisper, the awards ceremony often has long music/silence gaps where award announcements may be lost. Common FLL awards are: Core Values, Innovation Project, Robot Design, Robot Performance, and Champions Award. Flag any missing awards for the user to fill in from watching the video.
- **Awards in a separate video**: The main livestream may end before the awards ceremony (e.g., during a break for judges' deliberation). If the captions end without any awards content, ask the user if there's a separate awards video. Download and analyze that video's captions the same way.
- **Coach Mentor Award**: This is given to a coach/mentor, not a team. Note the coach's name and their team.
- **Rising All-Star Award**: This award may have multiple winners (not just one).
- **yt-dlp now requires a JS runtime** for YouTube. Use `--js-runtimes node --remote-components ejs:github`. To download a specific time window (much faster than the whole video for spot-checking a single match), use format 91 (144p HLS *with* audio) which downloads via ffmpeg at ~6-140×: `yt-dlp --js-runtimes node --remote-components ejs:github -N 16 -f 91 --download-sections "*H:MM:SS-H:MM:SS" -o "clip.%(ext)s" "URL"`. Format 91 HLS works reliably for windowed downloads; the DASH audio-only formats (140/251) are throttled and slow. (The older warning that `--download-sections` always fails applied to DASH formats — format 91 HLS works.)
- **Verifying/correcting a single match timestamp** (after the user spot-checks the draft): re-download just that ~9-minute window with format 91, re-transcribe it with **Whisper medium.en and `vad_filter=False`** (medium.en is far more accurate than base.en for countdowns, and disabling VAD prevents clipping the "3-2-1 lego" or detecting an adjacent buzzer instead). The full-video transcript is usually base.en for speed, but base.en mis-times or misses countdowns — never trust a base.en countdown for a final link without medium.en verification.
- **Confirm a timestamp with a video frame, anchoring on a running clock.** Extract a frame with `ffmpeg -ss <local_offset> -i clip.mp4 -frames:v 1 -q:v 3 -y out.jpg` (`local_offset = absolute_video_t − clip_start_offset`). The on-screen match timer counts down from **02:30**. A frame reading exactly 02:30 is ambiguous — the clock may be reset and *held* on an empty field before the match. Instead, find a frame where the timer reads **02:29 or less** (proving the clock is actively running), then compute the start time by working backwards: `start_t = frame_t − (150 − timer_remaining_seconds)`. For example, a frame at video t=9248 showing 02:26 means 4 s elapsed, so the match started at ~t=9244. Place the link a bit before that start depending on what the announcer is saying (see link-placement convention below).

### Verifying award winners with on-screen overlays

FLL livestreams typically display lower-third graphic overlays during the awards ceremony showing the award name and team number/name (e.g., "The Core Values Award goes to: 46068 - Past Patrol"). **Caption-based award identification is unreliable** because the announcer often misspeaks, the audio is muffled by music/applause, and Whisper VAD filtering drops awards-ceremony segments. **Always verify award winners against the on-screen overlay graphics.**

Workflow:

1. From the captions, extract approximate timestamps for each award announcement (search for award names: "core values", "innovation project", "robot design", "robot performance", "champions", "engineering excellence", "motivate", etc.).
2. **Beware of overlay lag.** The on-screen graphic typically appears 30-120 seconds AFTER the announcer says the award name. The runner-up names appear before the winner name, separated by 10-30 seconds each. Capture multiple frames in a window from `t+30` to `t+150` for each award.
3. Use Playwright to capture frames (1920×1080 viewport, headless). For each frame: load the YouTube URL with `?t=N`, accept cookies, click play+pause to load player, then `page.evaluate("video.currentTime = N")`, sleep 5s, and `video_element.screenshot()`.
4. **Resize frames before AI review.** Full 1920×1080 PNGs are ~1.5MB each. Convert to ~1280×720 JPEG quality 80 (~150KB each) using PIL: `img.thumbnail((1280, 720)); img.save(out, 'JPEG', quality=80)`. This dramatically reduces token cost when delegating verification to sub-agents.
5. **Delegate frame verification to multiple parallel sub-agents** (use Claude Haiku for cost). Group 5-10 frames per agent (e.g., one agent per award). Ask each agent to report exactly what overlay text is shown, including award name AND team number/name AND winner-vs-runner-up label.
6. **Always recapture failed frames.** If a frame comes back at 27KB or other tiny size, the YouTube player didn't load. Retry with a fresh page load (close and recreate the page object) instead of just re-seeking.
7. **⚠️ Sub-agent vision is not infallible.** A sub-agent may report "this overlay shows X" with high confidence when it actually shows Y. Cross-check by:
   - Capturing multiple frames at different timestamps for each award (2-5 frames spanning the winner/runner-up reveal).
   - If a sub-agent says an award doesn't exist, capture more frames in the gap before concluding it's missing — most awards have a 60-120s announcement window with multiple distinct overlays.
   - When a sub-agent's reading contradicts both the captions AND the typical FLL award lineup (e.g., "Motivate Award doesn't exist"), capture additional frames to verify before deleting content.
8. **Do not trust caption-derived award winners as final.** Always verify against at least one on-screen overlay frame per award.

### Placing and verifying match video links

The user reviews these links and will flag any that land in the wrong place. Apply these conventions:

- **Where to point the link:** aim ~6 seconds *before* the start countdown (countdown − 6) to catch the "thumbs up, three… two… one… lego" lead-in. Landing a little before the countdown is fine **as long as the commentary there is about the upcoming match** (e.g., the announcer naming the two teams, "we are good to go, refs ready"). Do NOT let a link land on the *previous* match's end buzzer, on dead air, or on an empty-field pause.
- **End-of-round mis-detections are common.** The last match or two of a round are the most error-prone because: (a) there's often a longer break/setup pause before them where the clock is reset to 02:30 on an empty field (Whisper VAD may detect this pause's "here we go" as the start), and (b) the previous match's *end* buzzer ("five, four, three, two, one… at the buzzer, stop") can be mis-detected as the next *start* countdown. Always verify the final matches of each round with medium.en + a frame, not just the base.en transcript.
- **Queue-call gotcha (reminder):** the announcer names UPCOMING teams to queue them to tables 2-3 minutes *before* they play. Confirm a team→timestamp mapping using the in-match play-by-play (teams named *while robots are running*), never the queue call.
- **Spot-check spacing:** within a round, countdowns are typically 3-5 min apart. A much larger gap (e.g., 7 min) usually means a genuine break before the final matches — not an error — but it's exactly where mis-detections cluster, so verify those matches explicitly.

### Verification checklist
After generating the page, verify:
1. Each team appears exactly once per round (except: the team missing from the cross-round's other round)
2. Scores on the page are copied correctly from the FLL Gameday API (match1/match2/match3 for each team). Note: scores come entirely from the API, not from the video.
3. START-END countdown pairs are ~140-160 seconds apart
4. The total number of detected start countdowns matches: (matches per round × number of rounds) accounting for sequential pods (e.g., 2 pods × 5 time slots = 10 countdowns per round). Plus any false starts, exhibition runs, or the opening ceremony kickoff. Some countdowns (~15-20%) may be missed by auto-captions — estimate those timestamps.
5. No countdown was misclassified as START when it's actually END (check for "five, four" before "three, two, one")
6. Add the tournament to `tournaments/fll/index.md` after creating the page

### Standard FLL awards
The typical awards given at FLL tournaments (in order of announcement):
1. **Core Values Award** — teamwork, discovery, inclusion, innovation, impact, fun
2. **Innovation Project Award** — best innovation project presentation
3. **Robot Design Award** — best robot mechanical/programming design
4. **Robot Performance Award** — highest robot game score
5. **Champions Award** — best overall team embodying the FLL experience (often advances)
6. **Advancing teams** — typically the Champions Award winner plus one or more additional teams

## Dependencies

```bash
pip install yt-dlp
```

For videos without auto-generated captions:
```bash
pip install faster-whisper
```

For scoreboard screenshots from video:
```bash
pip install playwright
python -m playwright install chromium
```
