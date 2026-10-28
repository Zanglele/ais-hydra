"""Retrospective route clustering + boundary-aware joint-window HYDRA extension."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans

from preprocessing import inspect_record, make_features, FEATURES, ROOT

sys.path.insert(0, str(ROOT / "HYDRA"))
from HYDRA.HYDRA_loader import HYDRA


def route_descriptor(arrays, points=16):
    """Ordered absolute positions in Earth-centred coordinates, kilometres.

    Resample by fractional path distance, not absolute observation time.
    Preserve location and direction; no translation/rotation normalisation.
    """
    lat, lon = np.deg2rad(arrays["lat"]), np.deg2rad(arrays["lon"])
    xyz = 6371.0088 * np.column_stack((np.cos(lat) * np.cos(lon),
                                     np.cos(lat) * np.sin(lon), np.sin(lat)))
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xyz, axis=0), axis=1))]
    if distance[-1] < 1e-8:
        return np.tile(xyz[0], points)
    unique, indices = np.unique(distance, return_index=True)
    grid = np.linspace(0, distance[-1], points)
    return np.column_stack([np.interp(grid, unique, xyz[indices, j])
                            for j in range(3)]).ravel()


def build_windows(arrays, win_size, stride):
    starts = np.arange(0, len(arrays) - win_size + 1, stride, dtype=np.int64)
    # Include final interval without crossing any trajectory boundary.
    if len(starts) and starts[-1] != len(arrays) - win_size:
        starts = np.r_[starts, len(arrays) - win_size]
    windows = np.stack([arrays[s:s + win_size].T.ravel() for s in starts])
    return windows.astype(np.float32), starts


def score_joint_windows(windows, win_size, backend, seed):
    """Reuse upstream hierarchy + its window-level max-z ensemble.

    Extension: input already contains windows from separate trajectories and
    shared cluster scaling. Never apply upstream reverse-windowing to this pool.
    The input/level normalisation scope differs from per-series HYDRA.
    """
    if len(windows) < 3:
        raise ValueError("At least three windows required")
    model = HYDRA(win_size, mode="approx", ann_backend=backend, random_state=seed)
    _, _, indexes = model.tree_compress_collect_levels(windows)
    levels = [model.level0.copy()]
    for index in indexes:
        dist, _ = index.kneighbors(windows, n_neighbors=1, return_distance=True)
        levels.append(dist.ravel())
    values = np.asarray(levels, dtype=np.float64)
    mean = values.mean(axis=1, keepdims=True)
    std = values.std(axis=1, keepdims=True)
    z = np.divide(values - mean, std, out=np.zeros_like(values), where=std > 1e-12)
    score = z.max(axis=0)
    if not np.isfinite(score).all():
        raise ValueError("Nonfinite HYDRA score")
    return score, len(levels), indexes[0].backend


def candidate_rows(key, record, cluster_id, starts, scores, percentiles, flags, threshold, window):
    """Export flagged windows plus unique covered points (not point-level detection).

    A covered point inherits the highest score of its covering flagged windows.
    This is a localisation aid, not a new score or a confirmed point anomaly.
    """
    windows, covered = [], {}
    for j in np.flatnonzero(flags):
        first, last = int(starts[j] + 1), int(starts[j] + window)
        windows.append(dict(
            trajectory_id=key, mmsi=record["mmsi"], cluster_id=int(cluster_id),
            original_start_point=first, original_end_point=last,
            window_start_utc=pd.to_datetime(record["timestamp"][first], unit="s", utc=True).isoformat(),
            window_end_utc=pd.to_datetime(record["timestamp"][last], unit="s", utc=True).isoformat(),
            start_latitude=float(record["lat"][first]), start_longitude=float(record["lon"][first]),
            end_latitude=float(record["lat"][last]), end_longitude=float(record["lon"][last]),
            hydra_score=float(scores[j]), cluster_percentile=float(percentiles[j]),
            cluster_threshold=float(threshold), candidate_flag=True,
            true_trajectory_label=record["anomaly_label"]))
        for point in range(first, last + 1):
            if point not in covered:
                covered[point] = [float(scores[j]), 1]
            else:
                covered[point][0] = max(covered[point][0], float(scores[j]))
                covered[point][1] += 1
    points = []
    for index, (score, count) in sorted(covered.items()):
        utc = pd.to_datetime(record["timestamp"][index], unit="s", utc=True)
        points.append(dict(
            trajectory_id=key, mmsi=record["mmsi"], cluster_id=int(cluster_id),
            original_point_index=index, time_utc=utc.isoformat(),
            time_beijing=utc.tz_convert("Asia/Shanghai").isoformat(),
            latitude=float(record["lat"][index]), longitude=float(record["lon"][index]),
            sog_knots=float(record["speed"][index]), cog_degrees=float(record["course"][index]),
            max_covering_window_score=score, covering_candidate_windows=count,
            candidate_flag=True, true_trajectory_label=record["anomaly_label"]))
    return windows, points


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=200, help="Random label-blind trajectory sample; 0=all")
    p.add_argument("--clusters", type=int, default=8)
    p.add_argument("--window", type=int, default=20, help="Feature points per window (2min spacing)")
    p.add_argument("--stride", type=int, default=5)
    p.add_argument("--quantile", type=float, default=.99, help="Exploratory within-cluster alert threshold")
    p.add_argument("--max-windows-per-cluster", type=int, default=200000)
    p.add_argument("--backend", choices=["auto", "hnsw", "sklearn"], default="auto")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=Path)
    p.add_argument("--plan-only", action="store_true", help="Inspect and cluster, report sizes without HYDRA scoring")
    args = p.parse_args()
    if args.limit < 0 or min(args.clusters, args.stride) < 1 or args.window < 2:
        p.error("limit>=0, clusters/stride>=1 and window>=2 required")
    if not 0 < args.quantile < 1 or args.max_windows_per_cluster < 3:
        p.error("0<quantile<1 and max-windows-per-cluster>=3 required")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = args.output or ROOT / "data/svalbard/results" / stamp
    out.mkdir(parents=True, exist_ok=False)  # Never overwrite an earlier run.
    config = vars(args).copy()
    config["output"] = str(out.resolve())
    config["method"] = "route_kmeans_joint_window_hydra_extension"
    (out / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    raw_path = ROOT / "data/svalbard/raw/formatted_trajectories.json"
    with raw_path.open(encoding="utf-8") as f:
        records = json.load(f)
    tracks, quality = [], []
    print("Inspecting all trajectories...", flush=True)
    for key, record in records.items():
        row, arrays = inspect_record(key, record)
        row["speed_review"] = row["speed_gt_60_count"] > 0
        quality.append(row)
        if row["eligible_for_features"] and row["n_points"] - 1 >= args.window:
            tracks.append((key, record, arrays))
    inventory = pd.DataFrame(quality)
    inventory.to_csv(out / "data_quality.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([r for r in quality if r["issues"] or r["speed_review"]]).to_csv(
        out / "data_quality_flags.csv", index=False, encoding="utf-8-sig")
    rng = np.random.default_rng(args.seed)
    eligible = len(tracks)
    if args.limit and len(tracks) > args.limit:
        chosen = np.sort(rng.choice(len(tracks), args.limit, replace=False))
        tracks = [tracks[i] for i in chosen]
    if len(tracks) < args.clusters:
        raise ValueError("Fewer eligible sampled trajectories than clusters")
    print(f"Clustering {len(tracks)} / {eligible} eligible trajectories...", flush=True)
    descriptors = np.stack([route_descriptor(t[2]) for t in tracks])
    clustering = MiniBatchKMeans(n_clusters=args.clusters, random_state=args.seed,
                                n_init=10, batch_size=1024)
    assignments = clustering.fit_predict(descriptors)
    np.savez_compressed(out / "route_clusters.npz", centres=clustering.cluster_centers_,
                        descriptors=descriptors, cluster_ids=assignments,
                        trajectory_ids=np.asarray([t[0] for t in tracks]))
    memberships = []
    for i, (key, record, arrays) in enumerate(tracks):
        memberships.append(dict(trajectory_id=key, mmsi=record["mmsi"],
                                ship_type=record.get("ship_type"), cluster_id=int(assignments[i]),
                                n_points=len(arrays["timestamp"]), true_label=record["anomaly_label"]))
    pd.DataFrame(memberships).to_csv(out / "cluster_membership.csv", index=False, encoding="utf-8-sig")
    # Check size before starting scoring, so no silent sampling/truncation occurs.
    plan = []
    for cid in np.unique(assignments):
        count = 0
        for i in np.flatnonzero(assignments == cid):
            n = len(tracks[i][2]["timestamp"]) - 1
            count += (n - args.window) // args.stride + 1 + int((n - args.window) % args.stride != 0)
        plan.append(dict(cluster_id=int(cid), trajectories=int(np.sum(assignments == cid)),
                         windows=count, window_matrix_mib=count * args.window * len(FEATURES) * 4 / 1024**2,
                         within_window_limit=count <= args.max_windows_per_cluster))
    pd.DataFrame(plan).to_csv(out / "execution_plan.csv", index=False, encoding="utf-8-sig")
    if args.plan_only:
        print(pd.DataFrame(plan).to_string(index=False), flush=True)
        print(f"Plan only; no scoring. All clusters within window limit: {all(r['within_window_limit'] for r in plan)}", flush=True)
        print(f"Results: {out.resolve()}", flush=True)
        return
    if not all(r["within_window_limit"] for r in plan):
        raise ValueError("Cluster windows exceed memory guard; see execution_plan.csv. "
                         "Increase stride/clusters, reduce limit, or explicitly increase guard.")
    all_track_rows, cluster_rows = [], []
    fields = ["trajectory_id", "mmsi", "cluster_id", "window_start_utc", "window_end_utc",
              "start_latitude", "start_longitude", "end_latitude", "end_longitude",
              "original_start_point", "original_end_point", "hydra_score", "cluster_percentile",
              "cluster_threshold", "candidate_flag", "true_trajectory_label"]
    point_fields = ["trajectory_id", "mmsi", "cluster_id", "original_point_index", "time_utc",
                    "time_beijing", "latitude", "longitude", "sog_knots", "cog_degrees",
                    "max_covering_window_score", "covering_candidate_windows", "candidate_flag",
                    "true_trajectory_label"]
    anomaly_file = out / "anomaly_candidates.csv"
    point_file = out / "anomaly_points.csv"
    pd.DataFrame(columns=fields).to_csv(anomaly_file, index=False, encoding="utf-8-sig")
    pd.DataFrame(columns=point_fields).to_csv(point_file, index=False, encoding="utf-8-sig")
    candidate_point_count = 0
    for cid in np.unique(assignments):
        indices = np.flatnonzero(assignments == cid)
        features = [make_features(tracks[i][2]) for i in indices]
        pooled = np.concatenate(features)
        mean, std = pooled.mean(axis=0, dtype=np.float64), pooled.std(axis=0, dtype=np.float64)
        std[std < 1e-8] = 1.
        parts, starts, owners, boundaries = [], [], [], [0]
        for i, x in zip(indices, features):
            w, positions = build_windows((x - mean) / std, args.window, args.stride)
            parts.append(w)
            starts.append(positions)
            owners.extend([i] * len(w))
            boundaries.append(boundaries[-1] + len(w))
        windows = np.concatenate(parts)
        positions = np.concatenate(starts)
        owners = np.asarray(owners, dtype=np.int64)
        if len(windows) < 3:
            for i in indices:
                all_track_rows.append(dict(**memberships[i], status="insufficient_cluster_windows"))
            continue
        print(f"Scoring cluster {cid}: {len(indices)} trajectories, {len(windows)} windows", flush=True)
        scores, n_levels, backend = score_joint_windows(windows, args.window, args.backend, args.seed)
        threshold = float(np.quantile(scores, args.quantile))
        flags = scores > threshold  # Strict: constant scores do not generate alerts.
        ordered = np.sort(scores)
        percentile = (np.searchsorted(ordered, scores, side="left") +
                      np.searchsorted(ordered, scores, side="right")) / (2 * len(scores))
        np.savez_compressed(out / f"cluster_{cid}_scores.npz", scores=scores, flags=flags,
                            cluster_percentiles=percentile, owner_indices=owners,
                            feature_start_indices=positions, threshold=threshold,
                            channel_mean=mean, channel_std=std)
        cluster_rows.append(dict(cluster_id=int(cid), trajectories=len(indices), windows=len(windows),
                                 levels=n_levels, backend=backend, threshold=threshold,
                                 flagged_windows=int(flags.sum())))
        candidates, candidate_points = [], []
        for local, i in enumerate(indices):
            lo, hi = boundaries[local:local + 2]
            ss = scores[lo:hi]
            top = max(1, int(np.ceil(len(ss) * .1)))
            all_track_rows.append(dict(**memberships[i], status="scored", windows=len(ss),
                                       max_score=float(ss.max()),
                                       top10pct_mean_score=float(np.sort(ss)[-top:].mean()),
                                       flagged_windows=int(flags[lo:hi].sum()),
                                       flagged_fraction=float(flags[lo:hi].mean()),
                                       cluster_threshold=threshold))
            window_rows, point_rows = candidate_rows(
                tracks[i][0], tracks[i][1], cid, positions[lo:hi], scores[lo:hi],
                percentile[lo:hi], flags[lo:hi], threshold, args.window)
            candidates.extend(window_rows)
            candidate_points.extend(point_rows)
        pd.DataFrame(candidates, columns=fields).to_csv(anomaly_file, mode="a", header=False, index=False, encoding="utf-8")
        pd.DataFrame(candidate_points, columns=point_fields).to_csv(point_file, mode="a", header=False, index=False, encoding="utf-8")
        candidate_point_count += len(candidate_points)
        del windows, pooled, parts, features
    pd.DataFrame(all_track_rows).to_csv(out / "trajectory_scores.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(cluster_rows).to_csv(out / "cluster_summary.csv", index=False, encoding="utf-8-sig")
    summary = dict(run_status="completed", raw_trajectories=len(records),
                   excluded_data_quality=int((~inventory.eligible_for_features).sum()),
                   excluded_below_window=int((inventory.eligible_for_features & (inventory.n_points - 1 < args.window)).sum()),
                   sampled_trajectories=len(tracks), eligible_trajectories=eligible,
                   scored_trajectories=sum(r["status"] == "scored" for r in all_track_rows),
                   sampled_anomaly_labels=sum(t[1]["anomaly_label"] for t in tracks),
                   flagged_windows=sum(r["flagged_windows"] for r in cluster_rows),
                   candidate_covered_points=candidate_point_count,
                   feature_names=FEATURES,
                   notes=["Exploratory retrospective extension, not original HYDRA reproduction.",
                          "Labels used only for output annotation, never clustering/scoring/threshold selection.",
                          "Threshold quantile is a review budget, not an estimated true anomaly rate.",
                          "Overlapping flagged windows are candidates, not independent confirmed events.",
                          "anomaly_points.csv lists points covered by candidate windows, not independently detected point anomalies.",
                          "Scores and percentiles are relative to each cluster, not calibrated probabilities.",
                          "No weather/accident inference and no point-level label evaluation.",
                          "Overlapping neighbours are retained as in upstream; no temporal exclusion zone.",
                          "KMeans forces assignment and may absorb unusual routes; compare with no-clustering baseline.",
                          "Clusters and scaling use the whole sampled batch: not a real-time or held-out evaluation."])
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Results: {out.resolve()}", flush=True)


if __name__ == "__main__":
    main()
