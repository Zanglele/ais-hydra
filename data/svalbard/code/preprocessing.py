"""Inspect AIS trajectories and optionally export boundary-preserving features.

Run from any directory with the project's Python interpreter. No HYDRA scores
are produced here; labels are kept separate from the feature matrix.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
FIELDS = ("lat", "lon", "speed", "course", "timestamp")
FEATURES = ("east_velocity_m_s", "north_velocity_m_s", "sog_knots",
            "sin_cog", "cos_cog")


def inspect_record(key, record):
    issues = []
    arrays = {}
    for field in FIELDS:
        try:
            arrays[field] = np.asarray(record[field], dtype=np.float64)
            if arrays[field].ndim != 1:
                issues.append(f"not_vector:{field}")
        except (KeyError, TypeError, ValueError):
            issues.append(f"unreadable:{field}")
    lengths = {field: len(a) for field, a in arrays.items() if a.ndim == 1}
    n = lengths.get("timestamp", 0)
    if len(lengths) != len(FIELDS) or len(set(lengths.values())) != 1:
        issues.append("inconsistent_lengths")
    if n < 2:
        issues.append("too_short")
    if record.get("track_length") != n:
        issues.append("track_length_mismatch")
    label = record.get("anomaly_label")
    if label not in (0, 1):
        issues.append("invalid_label")
    for field, a in arrays.items():
        if not np.isfinite(a).all():
            issues.append(f"nonfinite:{field}")
    usable_shapes = len(lengths) == len(FIELDS) and len(set(lengths.values())) == 1
    row = dict(trajectory_id=key, mmsi=record.get("mmsi"), label=label,
               ship_type=record.get("ship_type"), n_points=n,
               duration_minutes=None, start_utc=None, end_utc=None,
               non_120s_intervals=0, nonpositive_intervals=0,
               speed_gt_60_count=0, speed_eq_102_2_count=0,
               max_speed_knots=None, course_large_jump_count=0)
    if usable_shapes and n >= 2:
        lat, lon, speed, course, t = (arrays[f] for f in FIELDS)
        dt = np.diff(t)
        row["non_120s_intervals"] = int(np.count_nonzero(~np.isclose(dt, 120)))
        row["nonpositive_intervals"] = int(np.count_nonzero(dt <= 0))
        if row["non_120s_intervals"]:
            issues.append("irregular_timestamps")
        if np.isfinite(t).all():
            row["duration_minutes"] = float((t[-1] - t[0]) / 60)
            row["start_utc"] = pd.to_datetime(t[0], unit="s", utc=True).isoformat()
            row["end_utc"] = pd.to_datetime(t[-1], unit="s", utc=True).isoformat()
        for name, invalid in (
            ("lat", (lat < -90) | (lat > 90)),
            ("lon", (lon < -180) | (lon > 180)),
            ("speed", speed < 0),
            ("course", (course < 0) | (course >= 360)),
        ):
            if invalid.any():
                issues.append(f"out_of_range:{name}")
        row["speed_gt_60_count"] = int(np.count_nonzero(speed > 60))
        row["speed_eq_102_2_count"] = int(np.count_nonzero(np.isclose(speed, 102.2)))
        row["max_speed_knots"] = float(np.max(speed)) if np.isfinite(speed).all() else None
        # Review flag only: can be a valid circular transition, not necessarily an error.
        row["course_large_jump_count"] = int(np.count_nonzero(np.abs(np.diff(course)) > 180))
    row["issues"] = ";".join(issues)
    row["eligible_for_features"] = not issues
    return row, arrays


def make_features(arrays):
    """Local spherical finite-difference velocity, plus SOG and circular COG.

    Feature row j represents the interval ending at original point j+1.
    No fabricated first displacement; the first point is omitted.
    """
    lat = np.deg2rad(arrays["lat"])
    lon = np.deg2rad(arrays["lon"])
    dt = np.diff(arrays["timestamp"])
    dlon = (np.diff(lon) + np.pi) % (2 * np.pi) - np.pi
    east = 6371008.8 * np.cos((lat[1:] + lat[:-1]) / 2) * dlon / dt
    north = 6371008.8 * np.diff(lat) / dt
    angle = np.deg2rad(arrays["course"][1:])
    return np.column_stack((east, north, arrays["speed"][1:],
                            np.sin(angle), np.cos(angle))).astype(np.float32)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/svalbard/raw")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/svalbard/reports")
    parser.add_argument("--processed-dir", type=Path, default=ROOT / "data/svalbard/processed")
    parser.add_argument("--prepare", action="store_true", help="Also export features and offsets")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = args.raw_dir / "formatted_trajectories.json"
    with source.open(encoding="utf-8") as f:
        records = json.load(f)
    # This file is JSON Lines, despite its .json extension.
    ships = pd.read_json(args.raw_dir / "df_ships.json", lines=True)
    rows, feature_parts, ids, labels, mmsis = [], [], [], [], []
    timestamps, offsets = [], [0]
    total_points = 0
    for key, record in records.items():
        row, arrays = inspect_record(key, record)
        rows.append(row)
        total_points += row["n_points"]
        if args.prepare and row["eligible_for_features"]:
            x = make_features(arrays)
            if not np.isfinite(x).all():
                raise ValueError(f"Nonfinite generated features: {key}")
            feature_parts.append(x)
            timestamps.append(arrays["timestamp"][1:])
            offsets.append(offsets[-1] + len(x))
            ids.append(key)
            labels.append(record["anomaly_label"])
            mmsis.append(str(record["mmsi"]))
    frame = pd.DataFrame(rows)
    frame.to_csv(args.output_dir / "trajectory_inventory.csv", index=False, encoding="utf-8-sig")
    frame.loc[frame.label == 1].to_csv(args.output_dir / "labelled_anomalies.csv", index=False, encoding="utf-8-sig")
    issue_counts = Counter(issue for row in rows for issue in row["issues"].split(";") if issue)
    def quantiles(column):
        return {str(q): float(v) for q, v in frame[column].quantile([0, .25, .5, .75, .95, 1]).items()}
    summary = dict(
        source=str(source.resolve()), trajectories=len(frame), total_points=total_points,
        unique_vessels=int(frame.mmsi.nunique()), ship_metadata_records=len(ships),
        labels={str(k): int(v) for k, v in frame.label.value_counts(dropna=False).items()},
        points_quantiles=quantiles("n_points"), duration_minutes_quantiles=quantiles("duration_minutes"),
        issue_counts=dict(issue_counts),
        flagged_speed_gt_60_trajectories=int((frame.speed_gt_60_count > 0).sum()),
        flagged_speed_eq_102_2_trajectories=int((frame.speed_eq_102_2_count > 0).sum()),
        eligible_trajectories=int(frame.eligible_for_features.sum()),
        excluded_label_counts={str(k): int(v) for k, v in frame.loc[~frame.eligible_for_features, "label"].value_counts().items()},
        eligible_for_windows={str(w): int((frame.eligible_for_features & (frame.n_points - 1 >= w + 2)).sum()) for w in [10, 20, 30, 64]},
        notes=["Labels are trajectory-level, not point-level.",
               "Speed >60 and speed=102.2 are review flags only, not exclusions.",
               "Eligibility requires aligned finite arrays, regular 120s timestamps and valid ranges.",
               "No missing values are imputed; ineligible trajectories remain in the raw data and inventory.",
               "Window eligibility requires at least 3 windows (stride=1), not a recommendation of window size."])
    if args.prepare:
        args.processed_dir.mkdir(parents=True, exist_ok=True)
        if not feature_parts:
            raise ValueError("No eligible trajectories")
        np.savez_compressed(args.processed_dir / "features.npz",
                            features=np.concatenate(feature_parts), offsets=np.asarray(offsets, dtype=np.int64),
                            trajectory_ids=np.asarray(ids), labels=np.asarray(labels, dtype=np.int8),
                            mmsis=np.asarray(mmsis), timestamps=np.concatenate(timestamps),
                            feature_names=np.asarray(FEATURES))
        metadata = dict(feature_names=FEATURES, feature_dtype="float32", prepared_trajectories=len(ids),
                        prepared_points=offsets[-1],
                        layout="Trajectory i = features[offsets[i]:offsets[i+1]]. Never window across offsets.",
                        coordinates="Spherical local finite differences, radius 6371008.8m; not an ellipsoidal geodesic.",
                        first_point="Omitted: feature rows correspond to original points 1..N-1.",
                        scaling="None applied. Original HYDRA internally standardizes each channel of its input.",
                        labels="Stored separately; never include labels or MMSI in input features.",
                        caution="Preprocessing only; separate per-trajectory HYDRA scores are not calibrated across trajectories.")
        (args.processed_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        summary["processed_file"] = str((args.processed_dir / "features.npz").resolve())
    (args.output_dir / "data_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
