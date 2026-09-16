---
name: ftc-scorecard-generator
description: Generate FTC match scorecard and rankings images by screenshotting the official FTC events website. Use this skill when asked to create FTC match result images, score cards, or rankings screenshots.
---

# FTC Scorecard Generator

This skill generates professional 1920×1080 PNG images of FTC match results and rankings by screenshotting the official FTC events website and compositing them onto a branded background.

## When to use this skill

- When the user asks to generate FTC match scorecard images
- When the user asks to create FTC rankings screenshots
- When preparing match result images for video editing or social media
- When the user references FTC events pages and wants clean screenshots

## How to use

The script is at `.claude/skills/ftc-scorecard-generator/generate_scorecard.py`.

### Prerequisites

```bash
pip install playwright Pillow numpy
python -m playwright install chromium
```

### Single scorecard from a URL

```bash
python .claude/skills/ftc-scorecard-generator/generate_scorecard.py \
  --url https://ftc-events.firstinspires.org/2025/USARLRAS/qualifications/1 \
  --output scorecard_q1.png
```

### Generate all scorecards for an event (batch mode)

```bash
python .claude/skills/ftc-scorecard-generator/generate_scorecard.py \
  --event-code USARLRAS --season 2025 --output-dir scorecards/
```

This generates scorecards for all qualification matches (1-10), playoff matches, and the rankings page.

### Generate rankings only

```bash
python .claude/skills/ftc-scorecard-generator/generate_scorecard.py \
  --url https://ftc-events.firstinspires.org/2025/USARLRAS/rankings \
  --output rankings.png
```

### Specific qualification matches only

```bash
python .claude/skills/ftc-scorecard-generator/generate_scorecard.py \
  --event-code USARLRAS --season 2025 --qual-matches 1,4,5,7,9
```

## FTC Events URL patterns

- **Qualifications**: `https://ftc-events.firstinspires.org/{season}/{event_code}/qualifications/{match_number}`
- **Playoffs**: `https://ftc-events.firstinspires.org/{season}/{event_code}/playoff/{series}/{match_number}`
- **Rankings**: `https://ftc-events.firstinspires.org/{season}/{event_code}/rankings`

## Output

- 1920×1080 PNG images suitable for video editing or YouTube
- White content area with official FTC branding (Decode + FIRST logos)
- Blue gradient background (#003974 → #6CC2C9 → #003974)
- Scrolling team names are automatically fixed to static wrapped text
- Cookie banners, navigation, breakdowns, and other UI clutter are removed

## Technical details

- Uses Playwright (Chromium) to load and screenshot the actual FTC events website
- Pillow for cropping, scaling, and compositing onto the gradient background
- NumPy for efficient content boundary detection
- Handles both qualification (with ranking points) and playoff (without) pages
