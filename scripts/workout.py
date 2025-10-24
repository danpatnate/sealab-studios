#!/usr/bin/env python3
"""
Workout Tracker CLI using SQLite.

Commands:
  - init: Create database and tables
  - add-exercise: Add a new exercise definition
  - log: Record a set (exercise, weight, reps, RPE, notes)
  - list-workouts: List workouts with totals and optional details
  - summary: Show per-exercise stats or details for a specific exercise
  - prs: Show personal records by exercise (best e1RM)

DB path resolves as:
  1) --db PATH if passed
  2) $WORKOUT_DB_PATH if set
  3) <repo_root>/workouts.db (default)

All weights are stored canonically in kilograms (kg). Inputs in pounds are
converted using 1 lb = 0.45359237 kg.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional, Tuple

LB_TO_KG = 0.45359237


# --------------------------- Utilities ------------------------------------

def resolve_default_db_path() -> Path:
    # Default to repo root /workouts.db (assuming this file under scripts/)
    current_file = Path(__file__).resolve()
    repo_root = current_file.parent.parent
    return repo_root / "workouts.db"


def get_db_path(cli_db: Optional[str]) -> Path:
    if cli_db:
        return Path(cli_db).expanduser().resolve()
    env = os.environ.get("WORKOUT_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return resolve_default_db_path()


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # Enforce foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS exercises (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            primary_muscle TEXT,
            secondary_muscles TEXT
        );

        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,                 -- YYYY-MM-DD (local)
            start_time TEXT NOT NULL,           -- ISO8601
            end_time TEXT,                      -- ISO8601
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS sets (
            id INTEGER PRIMARY KEY,
            workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
            exercise_id INTEGER NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
            timestamp TEXT NOT NULL,            -- ISO8601
            input_weight REAL,
            input_unit TEXT,                    -- 'kg' | 'lb'
            weight_kg REAL NOT NULL,
            reps INTEGER NOT NULL,
            rpe REAL,
            notes TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_sets_exercise ON sets(exercise_id);
        CREATE INDEX IF NOT EXISTS idx_sets_workout ON sets(workout_id);
        CREATE INDEX IF NOT EXISTS idx_sets_timestamp ON sets(timestamp);
        """
    )
    conn.commit()


# --------------------------- Domain types ---------------------------------

@dataclass
class Exercise:
    id: int
    name: str
    primary_muscle: Optional[str]
    secondary_muscles: Optional[str]


# -------------------------- Domain helpers --------------------------------

def find_exercise_by_name(conn: sqlite3.Connection, name: str) -> Optional[Exercise]:
    row = conn.execute(
        "SELECT id, name, primary_muscle, secondary_muscles FROM exercises WHERE name = ?",
        (name,),
    ).fetchone()
    if not row:
        return None
    return Exercise(
        id=row["id"],
        name=row["name"],
        primary_muscle=row["primary_muscle"],
        secondary_muscles=row["secondary_muscles"],
    )


def add_or_update_exercise(
    conn: sqlite3.Connection,
    name: str,
    primary_muscle: Optional[str],
    secondary_muscles: Optional[str],
) -> Exercise:
    existing = find_exercise_by_name(conn, name)
    if existing:
        # Update existing row with any provided fields
        conn.execute(
            "UPDATE exercises SET primary_muscle = COALESCE(?, primary_muscle), secondary_muscles = COALESCE(?, secondary_muscles) WHERE id = ?",
            (primary_muscle, secondary_muscles, existing.id),
        )
        conn.commit()
        return Exercise(existing.id, name, primary_muscle or existing.primary_muscle, secondary_muscles or existing.secondary_muscles)
    cur = conn.execute(
        "INSERT INTO exercises (name, primary_muscle, secondary_muscles) VALUES (?,?,?)",
        (name, primary_muscle, secondary_muscles),
    )
    conn.commit()
    return Exercise(cur.lastrowid, name, primary_muscle, secondary_muscles)


def get_or_create_workout_for_date(
    conn: sqlite3.Connection,
    d: date,
    set_time: datetime,
) -> int:
    d_str = d.isoformat()
    row = conn.execute(
        "SELECT id, start_time, end_time FROM workouts WHERE date = ? ORDER BY id DESC LIMIT 1",
        (d_str,),
    ).fetchone()
    now_iso = set_time.isoformat(timespec="seconds")
    if row:
        workout_id = row["id"]
        # Extend end_time if needed
        if row["end_time"] is None or now_iso > row["end_time"]:
            conn.execute(
                "UPDATE workouts SET end_time = ? WHERE id = ?",
                (now_iso, workout_id),
            )
            conn.commit()
        return workout_id
    cur = conn.execute(
        "INSERT INTO workouts (date, start_time, end_time) VALUES (?,?,?)",
        (d_str, now_iso, now_iso),
    )
    conn.commit()
    return cur.lastrowid


def epley_e1rm(weight_kg: float, reps: int) -> float:
    if reps <= 1:
        return float(weight_kg)
    return float(weight_kg * (1.0 + reps / 30.0))


# --------------------------- Command impls --------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    db_path = get_db_path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        ensure_schema(conn)
    print(f"Initialized database at: {db_path}")


def cmd_add_exercise(args: argparse.Namespace) -> None:
    db_path = get_db_path(args.db)
    with connect(db_path) as conn:
        ensure_schema(conn)
        exercise = add_or_update_exercise(
            conn,
            name=args.name.strip(),
            primary_muscle=(args.primary.strip() if args.primary else None),
            secondary_muscles=(args.secondary.strip() if args.secondary else None),
        )
    print(f"Exercise ready: {exercise.name} (id={exercise.id})")


def cmd_log(args: argparse.Namespace) -> None:
    db_path = get_db_path(args.db)
    input_unit = args.unit.lower()
    if input_unit not in ("kg", "lb"):
        raise SystemExit("--unit must be 'kg' or 'lb'")

    # Parse date/time
    if args.date:
        try:
            d = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            raise SystemExit("--date must be YYYY-MM-DD")
    else:
        d = datetime.now().date()

    if args.time:
        try:
            t = datetime.strptime(args.time, "%H:%M").time()
        except ValueError:
            raise SystemExit("--time must be HH:MM (24h)")
        ts = datetime.combine(d, t)
    else:
        ts = datetime.now()

    weight = float(args.weight)
    reps = int(args.reps)
    if reps <= 0:
        raise SystemExit("--reps must be > 0")

    weight_kg = weight if input_unit == "kg" else weight * LB_TO_KG

    with connect(db_path) as conn:
        ensure_schema(conn)
        ex = find_exercise_by_name(conn, args.exercise)
        if not ex:
            raise SystemExit(
                f"Exercise '{args.exercise}' not found. Add it first with add-exercise."
            )

        # Workout handling
        if args.workout_id:
            workout_id = int(args.workout_id)
            # Update workout end_time if needed
            now_iso = ts.isoformat(timespec="seconds")
            conn.execute(
                "UPDATE workouts SET end_time = CASE WHEN end_time IS NULL OR ? > end_time THEN ? ELSE end_time END WHERE id = ?",
                (now_iso, now_iso, workout_id),
            )
            conn.commit()
        else:
            workout_id = get_or_create_workout_for_date(conn, d=d, set_time=ts)

        conn.execute(
            """
            INSERT INTO sets (workout_id, exercise_id, timestamp, input_weight, input_unit, weight_kg, reps, rpe, notes)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                workout_id,
                ex.id,
                ts.isoformat(timespec="seconds"),
                weight,
                input_unit,
                weight_kg,
                reps,
                (float(args.rpe) if args.rpe is not None else None),
                (args.notes if args.notes else None),
            ),
        )
        conn.commit()

    w = f" (workout {workout_id})" if args.verbose else ""
    print(
        f"Logged: {args.exercise}: {weight:g}{input_unit} x {reps} at {ts.isoformat(timespec='seconds')}{w}"
    )


def _date_range(where_from: Optional[str], where_to: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    from_str = None
    to_str = None
    if where_from:
        try:
            from_str = datetime.strptime(where_from, "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise SystemExit("--from must be YYYY-MM-DD")
    if where_to:
        try:
            to_str = datetime.strptime(where_to, "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise SystemExit("--to must be YYYY-MM-DD")
    return from_str, to_str


def human_duration(start_iso: str, end_iso: Optional[str]) -> str:
    try:
        start_dt = datetime.fromisoformat(start_iso)
    except Exception:
        return "-"
    if not end_iso:
        return "-"
    try:
        end_dt = datetime.fromisoformat(end_iso)
    except Exception:
        return "-"
    delta = end_dt - start_dt
    minutes = int(delta.total_seconds() // 60)
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours}h{mins:02d}m"
    return f"{mins}m"


def cmd_list_workouts(args: argparse.Namespace) -> None:
    db_path = get_db_path(args.db)
    from_str, to_str = _date_range(args.from_date, args.to_date)

    with connect(db_path) as conn:
        ensure_schema(conn)
        # Build filter
        filters = []
        params: list = []
        if from_str:
            filters.append("date >= ?")
            params.append(from_str)
        if to_str:
            filters.append("date <= ?")
            params.append(to_str)
        where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

        rows = conn.execute(
            f"SELECT id, date, start_time, end_time, notes FROM workouts {where_clause} ORDER BY date DESC, id DESC",
            tuple(params),
        ).fetchall()

        if not rows:
            print("No workouts found.")
            return

        for row in rows:
            workout_id = row["id"]
            # Aggregate
            agg = conn.execute(
                """
                SELECT COUNT(*) as set_count,
                       COUNT(DISTINCT exercise_id) as exercise_count,
                       SUM(weight_kg * reps) as volume_kg
                FROM sets WHERE workout_id = ?
                """,
                (workout_id,),
            ).fetchone()
            set_count = agg["set_count"] or 0
            exercise_count = agg["exercise_count"] or 0
            volume_kg = agg["volume_kg"] or 0.0

            print(
                f"Workout {workout_id} | {row['date']} | {human_duration(row['start_time'], row['end_time'])} | "
                f"sets: {set_count}, exercises: {exercise_count}, volume: {volume_kg:.0f} kg·reps"
            )
            if args.details:
                # Fetch details per exercise
                sets = conn.execute(
                    """
                    SELECT s.id, s.timestamp, e.name as exercise, s.input_weight, s.input_unit, s.reps, s.rpe, s.notes
                    FROM sets s
                    JOIN exercises e ON e.id = s.exercise_id
                    WHERE s.workout_id = ?
                    ORDER BY s.timestamp ASC, s.id ASC
                    """,
                    (workout_id,),
                ).fetchall()
                for s in sets:
                    rpe_str = f" RPE {s['rpe']:.1f}" if s["rpe"] is not None else ""
                    notes_str = f" — {s['notes']}" if s["notes"] else ""
                    print(
                        f"  [{s['timestamp']}] {s['exercise']}: {s['input_weight']:.2f}{s['input_unit']} x {s['reps']}{rpe_str}{notes_str}"
                    )


def _print_exercise_summary(conn: sqlite3.Connection, name: str, limit: int) -> None:
    ex = find_exercise_by_name(conn, name)
    if not ex:
        print(f"Exercise '{name}' not found.")
        return
    rows = conn.execute(
        """
        SELECT s.timestamp, s.weight_kg, s.reps, s.rpe, s.input_weight, s.input_unit
        FROM sets s
        WHERE s.exercise_id = ?
        ORDER BY s.timestamp DESC, s.id DESC
        LIMIT ?
        """,
        (ex.id, limit),
    ).fetchall()
    if not rows:
        print(f"No sets logged for {name} yet.")
        return

    print(f"Last {len(rows)} sets for {name}:")
    best_e1rm = 0.0
    best_desc = ""
    for r in rows:
        e1 = epley_e1rm(r["weight_kg"], int(r["reps"]))
        if e1 > best_e1rm:
            best_e1rm = e1
            best_desc = f"{r['input_weight']:.2f}{r['input_unit']} x {int(r['reps'])}"
        rpe_str = f" RPE {r['rpe']:.1f}" if r["rpe"] is not None else ""
        print(
            f"  [{r['timestamp']}] {r['input_weight']:.2f}{r['input_unit']} x {int(r['reps'])}{rpe_str}  (e1RM≈{e1:.1f} kg)"
        )
    print(f"Best recent e1RM: {best_e1rm:.1f} kg from {best_desc}")


def cmd_summary(args: argparse.Namespace) -> None:
    db_path = get_db_path(args.db)
    with connect(db_path) as conn:
        ensure_schema(conn)
        if args.exercise:
            _print_exercise_summary(conn, args.exercise, args.limit)
            return

        # Global summary per exercise
        rows = conn.execute(
            """
            SELECT e.name,
                   COUNT(s.id) as sets,
                   COUNT(DISTINCT s.workout_id) as sessions,
                   SUM(s.weight_kg * s.reps) as volume_kg,
                   MAX((s.weight_kg * (1.0 + s.reps / 30.0))) as best_e1rm
            FROM exercises e
            LEFT JOIN sets s ON s.exercise_id = e.id
            GROUP BY e.id
            ORDER BY e.name ASC
            """
        ).fetchall()
        if not rows:
            print("No exercises found.")
            return
        print("Exercise summary:")
        for r in rows:
            print(
                f"  {r['name']}: sets={r['sets'] or 0}, sessions={r['sessions'] or 0}, volume≈{(r['volume_kg'] or 0.0):.0f} kg·reps, best e1RM≈{(r['best_e1rm'] or 0.0):.1f} kg"
            )


def cmd_prs(args: argparse.Namespace) -> None:
    db_path = get_db_path(args.db)
    with connect(db_path) as conn:
        ensure_schema(conn)
        # Best e1RM per exercise with source set info
        rows = conn.execute(
            """
            SELECT e.name,
                   s.timestamp,
                   s.input_weight,
                   s.input_unit,
                   s.reps,
                   (s.weight_kg * (1.0 + s.reps / 30.0)) as e1rm
            FROM sets s
            JOIN exercises e ON e.id = s.exercise_id
            JOIN (
                SELECT exercise_id, MAX(weight_kg * (1.0 + reps / 30.0)) as max_e1rm
                FROM sets
                GROUP BY exercise_id
            ) m ON m.exercise_id = s.exercise_id AND m.max_e1rm = (s.weight_kg * (1.0 + s.reps / 30.0))
            ORDER BY e.name ASC
            """
        ).fetchall()
        if not rows:
            print("No PRs yet. Log some sets!")
            return
        print("Personal Records (best e1RM):")
        for r in rows:
            print(
                f"  {r['name']}: {r['input_weight']:.2f}{r['input_unit']} x {int(r['reps'])} on {r['timestamp']}  (e1RM≈{r['e1rm']:.1f} kg)"
            )


# ---------------------------- CLI setup -----------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Workout Tracker CLI")
    p.add_argument("--db", help="Path to SQLite DB (default: $WORKOUT_DB_PATH or workouts.db)")

    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="Initialize the database")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("add-exercise", help="Add or update an exercise")
    sp.add_argument("name", help="Exercise name (e.g., Bench Press)")
    sp.add_argument("--primary", help="Primary muscle group")
    sp.add_argument("--secondary", help="Secondary muscles (comma-separated)")
    sp.set_defaults(func=cmd_add_exercise)

    sp = sub.add_parser("log", help="Log a set for an exercise")
    sp.add_argument("--exercise", required=True, help="Exercise name (must exist)")
    sp.add_argument("--weight", required=True, type=float, help="Weight value in --unit")
    sp.add_argument("--reps", required=True, type=int, help="Repetitions")
    sp.add_argument("--unit", choices=["kg", "lb"], default="kg", help="Weight unit (default: kg)")
    sp.add_argument("--rpe", type=float, help="RPE value (optional)")
    sp.add_argument("--notes", help="Notes (optional)")
    sp.add_argument("--date", dest="date", help="Date YYYY-MM-DD (default: today)")
    sp.add_argument("--time", dest="time", help="Time HH:MM 24h (default: now)")
    sp.add_argument("--workout-id", help="Attach to existing workout id (optional)")
    sp.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("list-workouts", help="List workouts with summary totals")
    sp.add_argument("--from", dest="from_date", help="From date YYYY-MM-DD (inclusive)")
    sp.add_argument("--to", dest="to_date", help="To date YYYY-MM-DD (inclusive)")
    sp.add_argument("--details", action="store_true", help="Show per-set details")
    sp.set_defaults(func=cmd_list_workouts)

    sp = sub.add_parser("summary", help="Show per-exercise summary or details for one exercise")
    sp.add_argument("--exercise", help="Exercise name to show recent sets")
    sp.add_argument("--limit", type=int, default=10, help="Max recent sets for exercise (default: 10)")
    sp.set_defaults(func=cmd_summary)

    sp = sub.add_parser("prs", help="Show personal records by exercise (best e1RM)")
    sp.set_defaults(func=cmd_prs)

    return p


def main(argv: Optional[Iterable[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(args=argv)
    args.func(args)


if __name__ == "__main__":
    main()
