"""
FTC Scouting Watcher

Polls iCloud for new photos and the FTC API for new match results,
then triggers Copilot CLI to process scouting forms and update pages.
Run this as a background process during a tournament.

Usage:
    python .claude/skills/ftc-scouting-processor/scouting_watcher.py --event USARLCMP --season 2025
    python .claude/skills/ftc-scouting-processor/scouting_watcher.py --event USARLCMP --season 2025 --check 5

Requires:
    - icloud-credentials.json (git-ignored)
    - ftc-api-credentials.json (git-ignored)
    - pyicloud, pillow-heif, Pillow
    - Copilot CLI (copilot) installed and authenticated
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent.parent.parent  # .claude/skills/ftc-scouting-processor/ → repo root
INCOMING_DIR = REPO_DIR / "scouting" / "incoming"
STATE_FILE = INCOMING_DIR / "watcher_state.json"
POLL_INTERVAL = 30  # seconds
DEFAULT_PHOTOS_TO_CHECK = 20  # how many recent photos to check each poll

# Copilot session reuse — all invocations share one session so Copilot retains
# context about the event, team list, scouting data format, and page structure.
copilot_session_id = None


def get_icloud_api():
    """Connect to iCloud. Returns API object."""
    from pyicloud import PyiCloudService

    creds_path = REPO_DIR / "icloud-credentials.json"
    with open(creds_path) as f:
        creds = json.load(f)

    api = PyiCloudService(creds["apple_id"], creds["password"])

    if api.requires_2fa:
        print("2FA required. Requesting code...")
        api.request_2fa_code()
        code = input("Enter 2FA code from your device: ")
        result = api.validate_2fa_code(code)
        if result:
            api.trust_session()
            print("Session trusted!")
        else:
            print("2FA validation failed!")
            sys.exit(1)

    return api


def load_state():
    """Load watcher state (processed filenames, newest processed date, match count)."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"processed_files": [], "newest_processed": None, "known_match_count": 0, "schedule_posted": False}


def save_state(state):
    """Save watcher state."""
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def download_photo(photo, outdir):
    """Download a photo (medium version) and save as JPG."""
    outdir.mkdir(parents=True, exist_ok=True)

    stem = Path(photo.filename).stem

    # Use medium version: ~1500px, already JPEG, half the file size
    if "medium" in photo.versions:
        data = photo.download("medium")
        jpg_path = outdir / (stem + ".jpg")
        if data:
            with open(jpg_path, "wb") as f:
                f.write(data)
            return jpg_path

    # Fallback to original if no medium available
    data = photo.download()
    if not data:
        return None

    filename = photo.filename
    raw_path = outdir / filename
    with open(raw_path, "wb") as f:
        f.write(data)

    # Convert HEIC to JPG if needed
    if filename.upper().endswith(".HEIC"):
        from PIL import Image
        from pillow_heif import register_heif_opener

        register_heif_opener()
        img = Image.open(raw_path)
        jpg_path = outdir / (stem + ".jpg")
        img.save(jpg_path, quality=90)
        os.remove(raw_path)
        return jpg_path

    return raw_path


def check_schedule_available(season, event_code):
    """Check FTC API for qualification schedule. Returns True if schedule exists."""
    import base64
    import urllib.request

    creds_path = REPO_DIR / "ftc-api-credentials.json"
    if not creds_path.exists():
        return False

    with open(creds_path) as f:
        creds = json.load(f)

    token = base64.b64encode(
        (creds["username"] + ":" + creds["auth_key"]).encode()
    ).decode()
    headers = {"Authorization": "Basic " + token}

    try:
        url = "https://ftc-api.firstinspires.org/v2.0/%s/schedule/%s?tournamentLevel=qual" % (season, event_code)
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        schedule = data.get("schedule", [])
        return len(schedule) > 0
    except Exception as e:
        print(f"  Warning: Schedule check failed: {e}")
        return False


def run_copilot(prompt, label="task", timeout=300):
    """Invoke Copilot CLI, reusing the same session across calls.

    On the first call, starts a new session and captures its ID.
    Subsequent calls resume that session so Copilot retains context
    about the event, teams, scouting data format, and page structure.
    """
    global copilot_session_id

    cmd = ["copilot", "-p", prompt, "--autopilot", "--allow-all"]
    if copilot_session_id:
        cmd.extend(["--resume", copilot_session_id])
    else:
        cmd.extend(["--name", "scouting-watcher"])

    print(f"  Invoking Copilot CLI for {label}...")
    result = subprocess.run(
        cmd,
        cwd=str(REPO_DIR),
        timeout=timeout,
        capture_output=True,
        text=True,
    )

    # Capture the session ID from the first successful run
    if copilot_session_id is None and result.returncode == 0:
        # The session ID is a UUID in the output or can be found via session name
        # Use the named session for resume — Copilot supports --resume="name"
        copilot_session_id = "scouting-watcher"
        print(f"  Session established: {copilot_session_id}")

    if result.returncode == 0:
        print(f"  ✓ {label} completed")
    else:
        print(f"  ✗ {label} failed (code {result.returncode})")
        if result.stderr:
            print(f"    {result.stderr[:200]}")

    return result.returncode == 0


def post_schedule_with_copilot(season, event_code):
    """Invoke Copilot CLI to add the match schedule to the scouting page."""
    prompt = (
        f"The qualification match schedule is now available for event {event_code} (season {season}). "
        f"Using the ftc-scouting-processor skill, fetch the schedule from the FTC API "
        f"(endpoint: /v2.0/{season}/schedule/{event_code}?tournamentLevel=qual) "
        f"and update the scouting index page with the match pairings. "
        f"Then git add, commit, and push the changes."
    )
    return run_copilot(prompt, label="schedule update")


def check_new_matches(season, event_code, known_count):
    """Check FTC API for new match results. Returns (new_count, has_new)."""
    import base64
    import urllib.request

    creds_path = REPO_DIR / "ftc-api-credentials.json"
    if not creds_path.exists():
        return known_count, False

    with open(creds_path) as f:
        creds = json.load(f)

    token = base64.b64encode(
        (creds["username"] + ":" + creds["auth_key"]).encode()
    ).decode()
    headers = {"Authorization": "Basic " + token}

    try:
        url = "https://ftc-api.firstinspires.org/v2.0/%s/matches/%s" % (season, event_code)
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        scored = [m for m in data.get("matches", [])
                  if m.get("scoreRedFinal") is not None and m.get("scoreRedFinal") >= 0]
        current_count = len(scored)
        return current_count, current_count > known_count
    except Exception as e:
        print(f"  Warning: FTC API check failed: {e}")
        return known_count, False


def update_matches_with_copilot(season, event_code):
    """Invoke Copilot CLI to update scouting pages with new match results."""
    prompt = (
        f"New match results are available for event {event_code} (season {season}). "
        f"Using the ftc-scouting-processor skill, fetch the latest match results and rankings "
        f"from the FTC API, recalculate OPR, update the scouting index page "
        f"(match schedule, rankings, and OPR in the teams table). "
        f"Do NOT try to find livestream timestamps — those will be added later from the recorded video. "
        f"Then git add, commit, and push the changes."
    )
    return run_copilot(prompt, label="match update")


def process_with_copilot(photo_path):
    """Invoke Copilot CLI to process a scouting photo."""
    prompt = (
        f"Process the photo at {photo_path} using the ftc-scouting-processor skill. "
        f"If it's a scouting form, read the form data, update scouting-data.json, "
        f"update or create the team detail page, update the scouting index, "
        f"then git add, commit, and push the changes. "
        f"If it's a robot photo, identify the team number and save it to the team's scouting page. "
        f"If it's not a scouting form or robot photo, skip it — iCloud may include random personal photos."
    )
    return run_copilot(prompt, label=f"photo {Path(photo_path).name}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="FTC Scouting Watcher")
    parser.add_argument("--check", type=int, default=DEFAULT_PHOTOS_TO_CHECK,
                        help="Number of recent photos to check each poll (default: %d)" % DEFAULT_PHOTOS_TO_CHECK)
    parser.add_argument("--event", type=str, default=None,
                        help="FTC event code (e.g., USARLCMP) for match result polling")
    parser.add_argument("--season", type=str, default=None,
                        help="FTC season code (e.g., 2025)")
    args = parser.parse_args()
    photos_to_check = args.check

    print("FTC Scouting Watcher")
    print(f"Repo: {REPO_DIR}")
    print(f"Poll interval: {POLL_INTERVAL}s")
    print(f"Photos to check: {photos_to_check}")
    if args.event and args.season:
        print(f"Event: {args.event} (season {args.season})")
    else:
        print("No event specified — photo polling only (use --event and --season for match updates)")
    print(f"Incoming dir: {INCOMING_DIR}")
    print()

    api = get_icloud_api()
    state = load_state()
    processed = set(state["processed_files"])
    newest_processed = state.get("newest_processed")
    if newest_processed:
        newest_processed = datetime.fromisoformat(newest_processed)
    known_match_count = state.get("known_match_count", 0)

    print(f"Already processed: {len(processed)} photos")
    if newest_processed:
        print(f"Skipping photos older than: {newest_processed}")
    if args.event:
        print(f"Known scored matches: {known_match_count}")
        print(f"Schedule posted: {state.get('schedule_posted', False)}")
    print("Polling for new photos... (Ctrl+C to stop)\n")

    while True:
        try:
            all_photos = api.photos.all

            new_photos = []
            for i in range(photos_to_check):
                try:
                    p = all_photos[i]
                except IndexError:
                    break
                # Stop scanning once we hit photos older than our cutoff
                if newest_processed and p.added_date <= newest_processed:
                    break
                if p.filename in processed:
                    continue
                if p.item_type == "movie":
                    processed.add(p.filename)
                    continue
                new_photos.append(p)

            if new_photos:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(new_photos)} new photo(s)")

                for photo in reversed(new_photos):  # process oldest-first
                    print(f"  Downloading {photo.filename} ({photo.asset_date})...")
                    local_path = download_photo(photo, INCOMING_DIR)

                    if local_path:
                        success = process_with_copilot(local_path)
                        processed.add(photo.filename)

                        # Update newest processed date
                        if newest_processed is None or photo.added_date > newest_processed:
                            newest_processed = photo.added_date

                        state["processed_files"] = list(processed)
                        state["newest_processed"] = newest_processed.isoformat()
                        save_state(state)

                        if success:
                            print(f"  ✓ Processed {photo.filename}")
                        else:
                            print(f"  ✗ Failed to process {photo.filename}")

                print("Polling for new photos...")
            else:
                # Quiet poll — no output unless something new
                pass

            # Check for schedule and new match results
            if args.event and args.season:
                # Check for schedule if not yet posted
                if not state.get("schedule_posted", False):
                    if check_schedule_available(args.season, args.event):
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Match schedule is available!")
                        if post_schedule_with_copilot(args.season, args.event):
                            state["schedule_posted"] = True
                            save_state(state)

                # Check for new match results
                new_count, has_new = check_new_matches(args.season, args.event, known_match_count)
                if has_new:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] New match results! ({known_match_count} → {new_count} scored matches)")
                    update_matches_with_copilot(args.season, args.event)
                    known_match_count = new_count
                    state["known_match_count"] = known_match_count
                    save_state(state)

        except KeyboardInterrupt:
            print("\nStopping watcher.")
            break
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
