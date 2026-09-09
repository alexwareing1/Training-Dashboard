#!/usr/bin/env python3
"""
sync-hevy.py - pull every workout from the Hevy API and add any that aren't
already in hevyexportfullhistory.csv, written in that file's exact column format.

Usage:
    python3 sync-hevy.py [--dry-run]

    --dry-run   show what would be added, write nothing.

API key:
    Read from ".hevy-api-key" in this folder (first non-comment line). That file
    is gitignored and should be chmod 600. Set it up with:
        cp .hevy-api-key.example .hevy-api-key   # then edit in your key
    $HEVY_API_KEY still overrides it, but prefer the file - an env var passed on
    the command line ends up in your shell history.

Config:
    HEVY_TZ   IANA timezone the CSV timestamps are in (default Europe/London).
              The API returns UTC; Hevy's own CSV export writes wall-clock local
              time, so we convert every timestamp into this zone before
              formatting it. Set it to whatever your Hevy account uses.

What counts as "already there":
  * exact match on the formatted start_time  -> skipped silently
  * same calendar date + same workout title  -> skipped with a note printed
    (this catches a session the base export wrote in a different timezone)
Everything else is appended.

venue / sick columns:
    Hevy has no venue or sickness field, so put markers in the workout
    description (or any exercise note) and this script copies them across:
        #sick                -> sick   = True
        #guest:VenueName     -> venue  = VenueName
    The venue value runs to the end of the line or the next '#', ',' or ';',
    so either put #guest: last or separate it, e.g.
        "#sick #guest:Prime Fitness"  or  "#guest:Prime Fitness, felt rough".
    These columns are only written if the CSV header already has them.
"""
import csv, io, json, os, re, sys, time
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:                      # Python < 3.9
    ZoneInfo = None

HERE     = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "hevyexportfullhistory.csv")
KEY_PATH = os.path.join(HERE, ".hevy-api-key")   # untracked; see .hevy-api-key.example
API_BASE = "https://api.hevyapp.com/v1"
PAGE_SIZE = 10                           # API maximum


def _read_key_file(path):
    """First non-blank, non-comment line of the untracked key file, or ''."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    return ""


# $HEVY_API_KEY overrides, otherwise read the .hevy-api-key file. Don't pass the
# key on the command line - it lands in shell history.
API_KEY = os.environ.get("HEVY_API_KEY") or _read_key_file(KEY_PATH)
TZ_NAME = os.environ.get("HEVY_TZ", "Europe/London")

# Canonical columns we can produce. The file's own header decides which of
# these actually get written and in what order (see main()); venue/sick are
# dropped if the header doesn't carry them.
COLUMNS = ["title", "start_time", "end_time", "description", "exercise_title",
           "superset_id", "exercise_notes", "set_index", "set_type", "weight_kg",
           "reps", "distance_km", "duration_seconds", "rpe", "venue", "sick"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

TAG_SICK  = re.compile(r"#sick\b", re.I)
TAG_GUEST = re.compile(r"#guest:\s*([^\n#,;]+)", re.I)


# ---------------------------------------------------------------- helpers -----
def load_tz(name):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception as e:
            print(f"warning: can't load timezone {name!r} ({e}); using this "
                  f"machine's local time. `pip install tzdata` to fix.",
                  file=sys.stderr)
    else:
        print("warning: no zoneinfo module; using this machine's local time.",
              file=sys.stderr)
    return None                          # astimezone(None) == system local zone


def parse_iso(s):
    """Hevy timestamps: '2026-08-26T16:25:00Z' or with a numeric offset."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_dt(dt):
    """-> '26 Aug 2026, 17:25', matching the existing CSV (no leading zero on
    the day, English month abbreviation)."""
    return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}, {dt.hour:02d}:{dt.minute:02d}"


def parse_csv_dt(s):
    """Read the CSV's own '26 Aug 2026, 17:25' back into a datetime."""
    try:
        day, mon, rest = s.strip().split(" ", 2)
        year, hm = rest.split(", ")
        hh, mm = hm.split(":")
        return datetime(int(year), MONTHS.index(mon) + 1, int(day), int(hh), int(mm))
    except (ValueError, IndexError):
        return None


def num(v):
    """Numbers as the CSV writes them: 70, 82.5, 9.5 - integers without '.0',
    None/'' as empty."""
    if v is None or v == "":
        return ""
    f = float(v)
    if f.is_integer():
        return str(int(f))
    return f"{f:f}".rstrip("0").rstrip(".")


def api_get(path, params):
    url = f"{API_BASE}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "api-key": API_KEY,
        "Accept": "application/json",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit("Hevy API rejected the key (401). Check "
                                 "HEVY_API_KEY / the API_KEY constant.")
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                wait = 2 ** (attempt + 1)
                print(f"  HTTP {e.code}; retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise SystemExit(f"Hevy API error {e.code}: {e.read().decode(errors='replace')[:300]}")
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            raise SystemExit(f"Could not reach the Hevy API: {e}")
    raise SystemExit("Hevy API: retries exhausted.")


def fetch_all_workouts():
    first = api_get("/workouts", {"page": 1, "pageSize": PAGE_SIZE})
    pages = max(1, int(first.get("page_count", 1)))
    workouts = list(first.get("workouts", []))
    print(f"  fetched page 1/{pages}", file=sys.stderr)
    for page in range(2, pages + 1):
        time.sleep(1)                    # be gentle between pages
        data = api_get("/workouts", {"page": page, "pageSize": PAGE_SIZE})
        workouts.extend(data.get("workouts", []))
        print(f"  fetched page {page}/{pages}", file=sys.stderr)
    return workouts


def workout_tags(w):
    """Scan the workout description and every exercise note for #sick / #guest:
    markers. Returns (venue, sick_flag) as CSV-ready strings ('' when absent)."""
    text = " ".join([w.get("description") or ""]
                    + [e.get("notes") or "" for e in w.get("exercises", [])])
    m = TAG_GUEST.search(text)
    return (m.group(1).strip() if m else ""), ("True" if TAG_SICK.search(text) else "")


def workout_to_rows(w, tz):
    """One dict per set, keyed by CSV column name."""
    start = fmt_dt(parse_iso(w["start_time"]).astimezone(tz))
    end   = fmt_dt(parse_iso(w["end_time"]).astimezone(tz)) if w.get("end_time") else ""
    title = w.get("title") or ""
    desc  = w.get("description") or ""
    venue, sick = workout_tags(w)
    rows = []
    for ex in sorted(w.get("exercises", []), key=lambda e: e.get("index", 0)):
        ex_title = ex.get("title") or ""
        ex_notes = ex.get("notes") or ""
        superset = "" if ex.get("superset_id") is None else num(ex["superset_id"])
        for s in sorted(ex.get("sets", []), key=lambda s: s.get("index", 0)):
            dist = s.get("distance_meters")
            rows.append({
                "title": title, "start_time": start, "end_time": end,
                "description": desc, "exercise_title": ex_title,
                "superset_id": superset, "exercise_notes": ex_notes,
                "set_index": num(s.get("index")), "set_type": s.get("type") or "",
                "weight_kg": num(s.get("weight_kg")), "reps": num(s.get("reps")),
                "distance_km": "" if dist in (None, "") else num(float(dist) / 1000.0),
                "duration_seconds": num(s.get("duration_seconds")),
                "rpe": num(s.get("rpe")), "venue": venue, "sick": sick,
            })
    return rows


# ------------------------------------------------------------------- main -----
def main():
    dry_run = "--dry-run" in sys.argv[1:]

    if not API_KEY or API_KEY == "PASTE_YOUR_KEY_HERE":
        raise SystemExit(
            f"No API key. Put it on the first line of {KEY_PATH}\n"
            f"  cp .hevy-api-key.example .hevy-api-key && chmod 600 .hevy-api-key && "
            f"$EDITOR .hevy-api-key")
    if not os.path.exists(CSV_PATH):
        raise SystemExit(f"{CSV_PATH} not found.")

    tz = load_tz(TZ_NAME)

    # --- read the existing file, locate the real header, index what's there ---
    with open(CSV_PATH, "r", newline="", encoding="utf-8-sig") as f:
        lines = f.readlines()
    hi = next((i for i, ln in enumerate(lines)
               if "start_time" in ln and "exercise_title" in ln), None)
    if hi is None:
        raise SystemExit("No 'start_time,...' header row in the CSV - wrong file?")

    file_cols = next(csv.reader([lines[hi]]))
    missing = [c for c in ("venue", "sick") if c not in file_cols]
    if missing:
        print(f"note: CSV header has no {'/'.join(missing)} column - #sick / "
              f"#guest tags won't be recorded until it does.", file=sys.stderr)

    reader = csv.DictReader(lines[hi:])
    seen_start, seen_date_title = set(), set()
    for r in reader:
        st = (r.get("start_time") or "").strip()
        if not st:
            continue
        seen_start.add(st)
        d = parse_csv_dt(st)
        if d:
            seen_date_title.add((d.date(), (r.get("title") or "").strip()))

    # --- pull everything from the API --------------------------------------
    print("Fetching workouts from Hevy...", file=sys.stderr)
    workouts = fetch_all_workouts()
    print(f"  {len(workouts)} workouts on the account", file=sys.stderr)

    # --- decide which are new -------------------------------------------------
    fresh, notes, dup = [], [], 0
    for w in workouts:
        start_local = parse_iso(w["start_time"]).astimezone(tz)
        start_str = fmt_dt(start_local)
        key_dt = (start_local.date(), (w.get("title") or "").strip())
        if start_str in seen_start:
            dup += 1
            continue
        if key_dt in seen_date_title:
            notes.append(f"  note: {start_str} \"{key_dt[1]}\" looks already "
                         f"present for that date (different time string) - skipped")
            dup += 1
            continue
        w["_start_local"] = start_local
        fresh.append(w)

    for line in notes:
        print(line, file=sys.stderr)

    if not fresh:
        print(f"Up to date - {dup} workouts already in the CSV, nothing to add.")
        return

    # newest first, to match how the rest of the file is ordered
    fresh.sort(key=lambda w: w["_start_local"], reverse=True)
    new_rows = [row for w in fresh for row in workout_to_rows(w, tz)]

    print(f"\n{len(fresh)} new workout(s), {len(new_rows)} set row(s):")
    for w in fresh:
        n = sum(len(e.get("sets", [])) for e in w.get("exercises", []))
        print(f"  + {fmt_dt(w['_start_local'])}  {w.get('title') or '(untitled)'}  ({n} sets)")

    if dry_run:
        print("\n--dry-run: no changes written.")
        return

    # --- splice the new rows in right after the header, CRLF like the file --
    # DictWriter follows the file's own column order and silently drops any
    # column the header doesn't have (e.g. venue/sick on an older export).
    buf = io.StringIO()
    dw = csv.DictWriter(buf, fieldnames=file_cols, extrasaction="ignore",
                        restval="", lineterminator="\r\n")
    dw.writerows(new_rows)
    new_lines = buf.getvalue().splitlines(keepends=True)

    if not lines[hi].endswith(("\r\n", "\n")):     # guard a header with no EOL
        lines[hi] += "\r\n"
    out = lines[:hi + 1] + new_lines + lines[hi + 1:]

    tmp = CSV_PATH + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        f.writelines(out)
    os.replace(tmp, CSV_PATH)
    print(f"\nAppended {len(new_rows)} rows to {os.path.basename(CSV_PATH)}.")


if __name__ == "__main__":
    main()
