"""Find candidate YouTube videos for FTC season events that don't have one yet.

Usage (from the repo root):
    python .claude/skills/ftc-season-events/find_videos.py [--season 2026] [--days 21] [--no-search]

For every event in the window that has match results but no video (neither the API's
liveStreamUrl nor an entry in tools/ftc-stats/season-videos.json), this prints:
  - the event's website from the FTC API (check it for a stream link),
  - recent livestreams/uploads from the channels in channels.json dated near the event,
  - YouTube search results for the event name (unless --no-search).
Candidates are only suggestions: confirm the title, channel, date and description before adding
one to season-videos.json. It also lists recent FTC-looking videos on the channels that didn't
match any event, which can point to events or channels worth a closer look.
"""

import argparse
import base64
import datetime
import json
import os
import re
import subprocess
import urllib.parse
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
REPO = SKILL_DIR.parent.parent.parent
VIDEOS_JSON = REPO / "tools" / "ftc-stats" / "season-videos.json"

# yt-dlp needs a JS runtime for some YouTube videos; without it they fail as "not available".
YTDLP = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--ignore-errors",
         "--js-runtimes", "node", "--remote-components", "ejs:github"]
FTC_WORDS = re.compile(r"\b(FTC|BIOBUZZ|FIRST Tech|Tech Challenge|scrimmage|league meet|qualifier)\b", re.I)
STOP_WORDS = {"ftc", "the", "and", "of", "scrimmage", "event", "league", "meet", "day", "first", "tech",
              "challenge", "2026", "2027", "week", "robotics", "#1", "#2",
              # Region and league words that are shared by many events.
              "socal", "ntx", "ctx", "valley", "north", "south", "east", "west", "central", "northern", "southern",
              "school", "high", "academy", "center", "league"}


def api(season, path, headers):
    import urllib.request
    url = f"https://ftc-api.firstinspires.org/v2.0/{season}/{path}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as resp:
        return json.load(resp)


def auth_headers():
    creds = json.loads((REPO / "ftc-api-credentials.json").read_text())
    token = base64.b64encode(f"{creds['username']}:{creds['auth_key']}".encode()).decode()
    return {"Authorization": "Basic " + token}


def ytdlp_lines(args):
    # Force UTF-8 output; on Windows yt-dlp otherwise writes in the console code page.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(YTDLP + args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return [line for line in (result.stdout or "").splitlines() if line.strip()]


def channel_videos(handle, limit, today):
    """Recent streams and uploads from a channel.

    Dates come from YouTube's relative "N days/weeks/months ago" text, rounded down, so a video
    from "2 weeks ago" was really posted 14-20 days ago. `earliest` holds the start of that range.
    """
    videos = []
    for tab in ("streams", "videos"):
        for line in ytdlp_lines(["--flat-playlist", "--extractor-args", "youtubetab:approximate_date",
                                 "--playlist-end", str(limit),
                                 "--print", "%(id)s\t%(upload_date)s\t%(duration_string)s\t%(title)s",
                                 f"https://www.youtube.com/{handle}/{tab}"]):
            vid, date, duration, title = (line.split("\t", 3) + ["", "", ""])[:4]
            if not date[:8].isdigit():
                continue
            day = datetime.date(int(date[:4]), int(date[4:6]), int(date[6:8]))
            age = (today - day).days
            slack = 1 if age < 7 else 6 if age < 30 else 30
            videos.append(dict(id=vid, date=day, earliest=day - datetime.timedelta(days=slack),
                               duration=duration if duration != "NA" else "?", title=title, tab=tab))
    return videos


def search(query, limit=8):
    out = []
    # Sort by upload date (sp=CAI%3D); relevance ranking fills up with past seasons' videos.
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}&sp=CAI%3D"
    for line in ytdlp_lines(["--flat-playlist", "--playlist-end", str(limit),
                             "--print", "%(id)s\t%(channel)s\t%(title)s", url]):
        vid, channel, title = (line.split("\t", 2) + ["", ""])[:3]
        out.append(dict(id=vid, channel=channel, title=title))
    return out


def keywords(event):
    words = re.findall(r"[\w#'-]+", f"{event['name']} {event['city']}".lower())
    return {w for w in words if w not in STOP_WORDS and len(w) > 2}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--days", type=int, default=21, help="look at events that started in the last N days")
    parser.add_argument("--per-channel", type=int, default=15, help="recent videos to check per channel tab")
    parser.add_argument("--no-search", action="store_true", help="skip YouTube keyword searches")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    headers = auth_headers()
    today = datetime.date.today()
    since = today - datetime.timedelta(days=args.days)
    curated = json.loads(VIDEOS_JSON.read_text(encoding="utf-8"))
    channels = json.loads((SKILL_DIR / "channels.json").read_text(encoding="utf-8"))["channels"]

    events = []
    for e in api(args.season, "events", headers)["events"]:
        start = datetime.date.fromisoformat(e["dateStart"][:10])
        if e["typeName"] == "Kickoff" or not (since <= start <= today):
            continue
        matches = api(args.season, f"matches/{e['code']}", headers)["matches"]
        # Same "has a real result" rule as FtcStats.cs: posted, or started with a nonzero score.
        if not any(m.get("postResultTime") or m.get("actualStartTime") and ((m.get("scoreRedFinal") or 0) > 0 or (m.get("scoreBlueFinal") or 0) > 0)
                   for m in matches):
            continue
        e["_start"], e["_end"] = start, datetime.date.fromisoformat(e["dateEnd"][:10])
        e["_has_video"] = bool(e.get("liveStreamUrl") or curated.get(e["code"]))
        events.append(e)
    print(f"{len(events)} events with results since {since}; "
          f"{sum(not e['_has_video'] for e in events)} without a video.\n")

    print("Checking channels...", file=sys.stderr)
    recent = []
    for ch in channels:
        for v in channel_videos(ch["handle"], args.per_channel, today):
            if v["date"] >= since - datetime.timedelta(days=1):
                recent.append({**v, "channel": ch["name"]})

    matched = set()
    for e in sorted(events, key=lambda e: e["_start"]):
        # The video's possible posting dates overlap the event (or the couple of days after).
        near = [v for v in recent if v["earliest"] <= e["_end"] + datetime.timedelta(days=2)
                and v["date"] + datetime.timedelta(days=1) >= e["_start"]]
        words = keywords(e)
        hits = [v for v in near if words & set(re.findall(r"[\w#'-]+", v["title"].lower()))]
        matched.update(v["id"] for v in hits)
        if e["_has_video"]:
            continue
        print(f"== {e['code']}  {e['name'].strip()}  ({e['city']}, {e['stateprov']})  {e['_start']}")
        if e.get("website"):
            print(f"   website: {e['website'].strip()}")
        for v in hits:
            print(f"   channel match: https://www.youtube.com/watch?v={v['id']}  [{v['channel']}, ~{v['date']}, {v['duration']}]  {v['title']}")
        if not args.no_search:
            query = f"{e['name'].strip()} FTC {e['city']}"
            results = [r for r in search(query) if FTC_WORDS.search(r["title"]) and words & set(re.findall(r"[\w#'-]+", r["title"].lower()))]
            for r in results[:5]:
                print(f"   search: https://www.youtube.com/watch?v={r['id']}  [{r['channel']}]  {r['title']}")
            if not hits and not results:
                print("   nothing found")
        print()

    unmatched = [v for v in recent if v["id"] not in matched and FTC_WORDS.search(v["title"])]
    known = {re.search(r"[\w-]{11}", v["url"]).group(0) for vs in curated.values() if isinstance(vs, list) for v in vs}
    unmatched = [v for v in unmatched if v["id"] not in known]
    if unmatched:
        print("== Recent FTC-looking videos on the channels that didn't match an event")
        for v in sorted(unmatched, key=lambda v: v["date"], reverse=True):
            print(f"   https://www.youtube.com/watch?v={v['id']}  [{v['channel']}, ~{v['date']}, {v['duration']}]  {v['title']}")


if __name__ == "__main__":
    main()
