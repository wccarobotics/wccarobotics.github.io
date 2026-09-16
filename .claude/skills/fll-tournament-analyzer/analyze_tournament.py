"""
FLL Tournament Video Analyzer

Parses YouTube auto-generated captions (VTT format) to find match start
timestamps and identify team pairings. Cross-references with FLL Gameday
scoreboard data to produce a complete tournament analysis.

Usage:
    python analyze_tournament.py \
        --captions captions.en.vtt \
        --scores scores.json \
        --output analysis.json

    Or fetch scores directly:
    python analyze_tournament.py \
        --captions captions.en.vtt \
        --scoreboard-id 66601ff4-3def-4fac-bf7b-67697b2c5338 \
        --output analysis.json

Requirements:
    Python 3.8+ (standard library only)
"""

import argparse
import json
import re
import sys
import urllib.request
from collections import defaultdict


def parse_vtt(filepath):
    """Parse a VTT caption file into (timestamp_seconds, text) entries."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    entries = []
    current_ts = None
    current_text = []

    for line in lines:
        ts_match = re.match(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3}) --> ", line)
        if ts_match:
            if current_ts is not None and current_text:
                text = " ".join(current_text)
                text = re.sub(r"<[^>]+>", "", text)
                text = text.replace("&gt;&gt;", ">>").replace("&amp;", "&")
                entries.append((current_ts, text.strip()))
            h, m, s, ms = ts_match.groups()
            current_ts = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
            current_text = []
        elif line.strip() and not line.startswith(("WEBVTT", "Kind:", "Language:")):
            current_text.append(line.strip())

    if current_ts is not None and current_text:
        text = " ".join(current_text)
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&gt;&gt;", ">>").replace("&amp;", "&")
        entries.append((current_ts, text.strip()))

    # Deduplicate consecutive identical text
    deduped = []
    for ts, text in entries:
        if not deduped or text != deduped[-1][1]:
            deduped.append((ts, text))

    return deduped


def fetch_scoreboard(event_id):
    """Fetch scoreboard data from FLL Gameday API."""
    url = f"https://api.fllgameday.com/public/scoreboard/{event_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read().decode("utf-8"))


def fetch_event_info(event_id):
    """Fetch event info from FLL Gameday API."""
    url = f"https://api.fllgameday.com/public/event/{event_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = json.loads(urllib.request.urlopen(req).read().decode("utf-8"))
    return resp


def build_team_keywords(teams):
    """Build a mapping of search keywords to team IDs."""
    keywords = {}
    for team in teams:
        tid = team["customTeamId"]
        name = team["name"]

        # Add team number
        keywords[tid] = tid

        # Add full name and meaningful substrings (lowercased)
        name_lower = name.lower()
        keywords[name_lower] = tid

        # Split into individual words and use multi-word substrings
        words = name_lower.split()
        for word in words:
            if len(word) >= 4 and word not in (
                "the",
                "team",
                "first",
                "lego",
                "league",
                "school",
                "academy",
                "christian",
                "adventist",
            ):
                keywords[word] = tid

    return keywords


def find_countdowns(entries):
    """Find all countdown markers (match starts) in the captions."""
    countdowns = []
    for ts, text in entries:
        text_lower = text.lower()
        if re.search(
            r"three.{0,10}two.{0,10}one.{0,15}(let'?s go|go|start)", text_lower
        ):
            countdowns.append(ts)
        elif re.search(r"\b3.{0,5}2.{0,5}1.{0,10}(go|start|zero)", text_lower):
            countdowns.append(ts)

    # Deduplicate countdowns within 10 seconds of each other
    deduped = []
    for ts in sorted(countdowns):
        if not deduped or ts - deduped[-1] > 10:
            deduped.append(ts)

    return deduped


def find_teams_near_timestamp(entries, target_ts, team_keywords, window_before=120, window_after=30):
    """Find team references in captions near a given timestamp."""
    found = set()
    for ts, text in entries:
        if target_ts - window_before <= ts <= target_ts + window_after:
            text_lower = text.lower()
            for keyword, team_id in team_keywords.items():
                if keyword in text_lower:
                    found.add(team_id)
    return found


def group_into_rounds(match_starts, num_teams):
    """Group match timestamps into rounds based on timing gaps."""
    if not match_starts:
        return []

    matches_per_round = num_teams // 2
    rounds = []
    current_round = [match_starts[0]]

    for i in range(1, len(match_starts)):
        gap = match_starts[i] - match_starts[i - 1]
        # If the gap is significantly larger than normal match spacing,
        # or we already have enough matches for this round, start a new round
        if len(current_round) >= matches_per_round and gap > 180:
            rounds.append(current_round)
            current_round = [match_starts[i]]
        else:
            current_round.append(match_starts[i])

    if current_round:
        rounds.append(current_round)

    return rounds


def resolve_pairings(rounds, entries, teams, team_keywords):
    """Resolve team pairings for each match using captions and elimination."""
    all_team_ids = {t["customTeamId"] for t in teams}
    resolved_rounds = []

    for round_idx, match_starts in enumerate(rounds):
        used_teams = set()
        matches = []

        # First pass: find teams from captions
        for ts in match_starts:
            found = find_teams_near_timestamp(entries, ts, team_keywords)
            matches.append({"timestamp": ts, "found_teams": found, "pair": None})

        # Assign pairs from caption-identified teams
        for match in matches:
            candidates = match["found_teams"] - used_teams
            if len(candidates) >= 2:
                pair = sorted(candidates)[:2]
                match["pair"] = pair
                used_teams.update(pair)
            elif len(candidates) == 1:
                match["pair"] = [sorted(candidates)[0], None]
                used_teams.update(candidates)

        # Second pass: fill in gaps using elimination
        remaining = sorted(all_team_ids - used_teams)
        for match in matches:
            if match["pair"] is None:
                if len(remaining) >= 2:
                    match["pair"] = [remaining.pop(0), remaining.pop(0)]
                elif len(remaining) == 1:
                    match["pair"] = [remaining.pop(0), None]
            elif match["pair"][1] is None and remaining:
                match["pair"][1] = remaining.pop(0)

        resolved_rounds.append(matches)

    return resolved_rounds


def format_timestamp(seconds):
    """Format seconds as H:MM:SS or MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def find_awards_section(entries, teams, team_keywords):
    """Search the last portion of captions for awards ceremony content."""
    if not entries:
        return {}

    last_ts = entries[-1][0]
    awards_start = last_ts * 0.75  # Search last quarter of video

    award_keywords = [
        "award",
        "champion",
        "core value",
        "innovation",
        "robot design",
        "robot performance",
        "robot game",
        "advancing",
        "ceremony",
        "medal",
        "trophy",
    ]

    awards_entries = []
    for ts, text in entries:
        if ts >= awards_start:
            text_lower = text.lower()
            if any(kw in text_lower for kw in award_keywords):
                teams_found = set()
                for kw, tid in team_keywords.items():
                    if kw in text_lower:
                        teams_found.add(tid)
                awards_entries.append({
                    "timestamp": ts,
                    "text": text[:200],
                    "teams_found": sorted(teams_found),
                })

    return awards_entries


def main():
    parser = argparse.ArgumentParser(description="Analyze FLL tournament video captions")
    parser.add_argument("--captions", required=True, help="Path to VTT caption file")
    parser.add_argument("--scores", help="Path to JSON scores file (alternative to --scoreboard-id)")
    parser.add_argument("--scoreboard-id", help="FLL Gameday event UUID")
    parser.add_argument("--output", default="analysis.json", help="Output JSON file")
    args = parser.parse_args()

    # Load scores
    if args.scores:
        with open(args.scores, "r") as f:
            teams = json.load(f)
    elif args.scoreboard_id:
        print(f"Fetching scoreboard for {args.scoreboard_id}...")
        teams = fetch_scoreboard(args.scoreboard_id)
        event_info = fetch_event_info(args.scoreboard_id)
        print(f"Event: {event_info.get('name', 'Unknown')}")
    else:
        print("Error: Provide either --scores or --scoreboard-id", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(teams)} teams")
    for t in teams:
        print(f"  {t['customTeamId']} {t['name']} (rank {t['rank']})")

    # Parse captions
    print(f"\nParsing captions from {args.captions}...")
    entries = parse_vtt(args.captions)
    print(f"Parsed {len(entries)} caption entries")

    # Build keyword lookup
    team_keywords = build_team_keywords(teams)

    # Find countdowns (match starts)
    countdowns = find_countdowns(entries)
    print(f"\nFound {len(countdowns)} countdown markers:")
    for ts in countdowns:
        print(f"  {format_timestamp(ts)}")

    # Group into rounds
    rounds = group_into_rounds(countdowns, len(teams))
    print(f"\nGrouped into {len(rounds)} rounds:")
    for i, r in enumerate(rounds):
        print(f"  Round {i+1}: {len(r)} matches ({format_timestamp(r[0])} - {format_timestamp(r[-1])})")

    # Resolve pairings
    resolved = resolve_pairings(rounds, entries, teams, team_keywords)

    # Build team lookup
    team_lookup = {t["customTeamId"]: t for t in teams}

    # Build output
    output = {
        "event": event_info.get("name", "Unknown") if args.scoreboard_id else "Unknown",
        "teams": [
            {
                "id": t["customTeamId"],
                "name": t["name"],
                "rank": t["rank"],
                "highScore": t["highScore"],
                "practice": t.get("practice"),
                "match1": t.get("match1"),
                "match2": t.get("match2"),
                "match3": t.get("match3"),
            }
            for t in sorted(teams, key=lambda x: x["rank"])
        ],
        "rounds": [],
    }

    for round_idx, matches in enumerate(resolved):
        round_data = {"round": round_idx + 1, "matches": []}
        match_field = f"match{round_idx + 1}"

        for match in matches:
            pair = match.get("pair", [None, None])
            match_data = {
                "timestamp": format_timestamp(match["timestamp"]),
                "timestamp_seconds": int(match["timestamp"]),
            }

            for i, label in enumerate(["teamA", "teamB"]):
                tid = pair[i] if pair and i < len(pair) else None
                if tid and tid in team_lookup:
                    t = team_lookup[tid]
                    match_data[label] = {
                        "id": tid,
                        "name": t["name"],
                        "score": t.get(match_field, "?"),
                    }
                else:
                    match_data[label] = {"id": "???", "name": "Unknown", "score": "?"}

            round_data["matches"].append(match_data)

        output["rounds"].append(round_data)

    # Find awards
    awards_entries = find_awards_section(entries, teams, team_keywords)
    output["awards_hints"] = awards_entries[:30]

    # Write output
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nAnalysis written to {args.output}")
    print("\n=== MATCH SUMMARY ===")
    for round_data in output["rounds"]:
        print(f"\nRound {round_data['round']}:")
        for m in round_data["matches"]:
            a = m["teamA"]
            b = m["teamB"]
            print(f"  [{m['timestamp']}] {a['id']} {a['name']} ({a['score']}) & {b['id']} {b['name']} ({b['score']})")

    print("\n=== REVIEW CHECKLIST ===")
    print("1. Verify each team appears exactly once per round")
    print("2. Check for match redos (extra countdowns from clock malfunctions)")
    print("3. Look for awards ceremony details in the last portion of the video")
    print("4. Cross-reference team pairings with schedule if available")


if __name__ == "__main__":
    main()
