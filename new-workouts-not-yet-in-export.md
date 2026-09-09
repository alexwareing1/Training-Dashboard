# Workouts since the last Hevy export

Base export runs to **8 Sep 2026**. Add anything after that below, newest or
oldest first — order doesn't matter. If a date here already exists in the CSV,
the CSV wins and this entry is ignored, so it's always safe to re-export from
Hevy and clear this file.

## Format

    ## YYYY-MM-DD | Session name | HH:MM-HH:MM
    Exercise Name: 87.5x7, 82.5x8, 80x6, 40x4d

- One exercise per line, `weight x reps` separated by commas.
- Suffix a set with `d` for a drop set, `w` for a warm-up, `f` for failure.
  No suffix means a normal working set.
- Bodyweight lifts: leave the weight off — `Pull Up: x12, x10, x8`
- Times are optional but the session-length and time-of-day charts need them.
- Exercise names should match the ones already in the log. Close spellings get
  matched automatically; anything genuinely new gets flagged on rebuild.

<!-- Add new sessions below this line -->
