#!/usr/bin/env python3
"""
Compare a fixed-N GAMBIT scan (run with adaptive_log_only: true) with an
adaptive-stopping scan of the same model, using the hdf5_v1 printer output of
yaml_files/SUSYRun2_MSSMEW_fixedN.yaml and yaml_files/SUSYRun2_MSSMEW_adaptive.yaml.

Reports
  * cost:     events and operateLHCLoop runtime per point, speedup
  * fidelity: from the fixed-N scan, how often the stopping rule would have
              fired for points that, at full statistics, lie in the region of
              interest of the profile likelihood (these are the harmful stops)
  * profiles: best fit and 2D profile likelihood maps of both scans

Usage:
  compare_adaptive_scans.py FIXED.hdf5 ADAPTIVE.hdf5 [--outdir DIR] [--collider LHC_13TeV]
                            [--x M1 --y M2] [--roi 5.99]
"""

import argparse
import os
import sys

import h5py
import numpy as np

LOOPINFO = "#LHCEventLoopInfo @ColliderBit::getLHCEventLoopInfo::"
LHC_LOGLIKE = "#LHC_Combined_LogLike @ColliderBit::calc_combined_LHC_LogLike"
LOOP_RUNTIME = "Runtime(ns) for #RunMC @ColliderBit::operateLHCLoop"
REASONS = {0: "not stopped", 1: "excluded", 2: "insensitive"}


def load_scan(path, group, collider, params):
    """Return a dict of 1D arrays for the valid points of one scan."""
    with h5py.File(path, "r") as f:
        g = f[group]

        def column(name, required=True):
            if name not in g:
                if required:
                    sys.exit("Dataset '{0}' not found in {1}".format(name, path))
                return None
            return np.asarray(g[name][:], dtype=float), np.asarray(g[name + "_isvalid"][:], dtype=bool)

        def param_column(par):
            matches = [k for k in g.keys() if k.endswith("::" + par) and k.startswith("#") and "parameters" in k]
            if not matches:
                sys.exit("Parameter '{0}' not found in {1}".format(par, path))
            return column(matches[0])

        loglike, valid = column("LogLike")
        lhc, lhc_valid = column(LHC_LOGLIKE)
        valid &= lhc_valid
        data = {"LogLike": loglike, "LHC": lhc}

        for key in ["event_count", "adaptive_stop_reason", "adaptive_events_at_stop",
                    "adaptive_dlnL_upper_at_stop", "adaptive_n_checkpoints"]:
            data[key], ok = column(LOOPINFO + key + "_" + collider)
            valid &= ok

        runtime = column(LOOP_RUNTIME, required=False)
        if runtime is not None:
            data["loop_runtime_s"] = runtime[0] * 1e-9
            valid &= runtime[1]

        for par in params:
            data[par], ok = param_column(par)
            valid &= ok

    return {k: v[valid] for k, v in data.items()}


def summarise_cost(name, scan):
    """Print event and runtime statistics for one scan."""
    n_points = len(scan["LogLike"])
    events = scan["event_count"]
    print("\n== {0}: {1} valid points".format(name, n_points))
    print("   events/point:  mean {0:.3g}, median {1:.3g}, total {2:.4g}".format(events.mean(), np.median(events), events.sum()))
    if "loop_runtime_s" in scan:
        rt = scan["loop_runtime_s"]
        print("   operateLHCLoop runtime/point: mean {0:.1f} s, total {1:.1f} CPU-h (x threads)".format(rt.mean(), rt.sum() / 3600.))
    for code, label in REASONS.items():
        frac = np.mean(scan["adaptive_stop_reason"] == code) if n_points else 0.
        print("   adaptive decision '{0}': {1:.1%}".format(label, frac))


def speedup(fixed, adaptive):
    """Print per-point cost ratios between the two scans."""
    print("\n== Speedup (fixed / adaptive, per point)")
    print("   events:  {0:.2f}x".format(fixed["event_count"].mean() / adaptive["event_count"].mean()))
    if "loop_runtime_s" in fixed and "loop_runtime_s" in adaptive:
        print("   operateLHCLoop runtime:  {0:.2f}x".format(fixed["loop_runtime_s"].mean() / adaptive["loop_runtime_s"].mean()))


def fidelity_from_log_only(fixed, roi, threshold):
    """Use the log-only decisions of the fixed-N scan to count harmful stops.

    A stop is harmful if the point is inside the profile-likelihood region of
    interest at full statistics (LogLike within `roi` of the best fit), or if the
    full-statistics LHC delta lnL lies above the stopping threshold (bound violated).
    """
    would_stop = fixed["adaptive_stop_reason"] > 0
    in_roi = fixed["LogLike"] > fixed["LogLike"].max() - roi
    excluded = fixed["adaptive_stop_reason"] == 1
    bound_violated = excluded & (fixed["LHC"] > -threshold)

    print("\n== Fidelity (from the log-only decisions of the fixed-N scan)")
    print("   points where the rule would have stopped: {0} / {1}".format(would_stop.sum(), len(would_stop)))
    print("   ... inside the region of interest (dlnL < {0}): {1}".format(roi, (would_stop & in_roi).sum()))
    print("   ... 'excluded' stops with full-stat LHC dlnL > -{0}: {1}".format(threshold, bound_violated.sum()))
    if would_stop.any():
        events_saved = fixed["event_count"][would_stop] - fixed["adaptive_events_at_stop"][would_stop]
        print("   projected speedup in events: {0:.2f}x".format(
            fixed["event_count"].sum() / (fixed["event_count"].sum() - events_saved.sum())))


def profile_2d(scan, x, y, bins):
    """Profile likelihood (max LogLike) on a 2D grid, relative to the scan's best fit."""
    xi = np.clip(np.digitize(scan[x], bins[0]) - 1, 0, len(bins[0]) - 2)
    yi = np.clip(np.digitize(scan[y], bins[1]) - 1, 0, len(bins[1]) - 2)
    prof = np.full((len(bins[0]) - 1, len(bins[1]) - 1), -np.inf)
    np.maximum.at(prof, (xi, yi), scan["LogLike"])
    return prof - scan["LogLike"].max()


def compare_profiles(fixed, adaptive, x, y, outdir, n_bins=60):
    """Print best fits and contour overlap; plot both 2D profiles if matplotlib is available."""
    print("\n== Profiles")
    for name, scan in [("fixed", fixed), ("adaptive", adaptive)]:
        best = np.argmax(scan["LogLike"])
        print("   {0:9s} best fit LogLike = {1:.3f} at {2} = {3:.1f}, {4} = {5:.1f}".format(
            name, scan["LogLike"][best], x, scan[x][best], y, scan[y][best]))

    both = np.concatenate([fixed[x], adaptive[x]]), np.concatenate([fixed[y], adaptive[y]])
    bins = [np.linspace(v.min(), v.max(), n_bins + 1) for v in both]
    profiles = {name: profile_2d(scan, x, y, bins) for name, scan in [("fixed", fixed), ("adaptive", adaptive)]}

    # 2D 1 and 2 sigma regions: dlnL > -1.15, -3.09
    for label, level in [("1 sigma", -1.15), ("2 sigma", -3.09)]:
        a, b = profiles["fixed"] > level, profiles["adaptive"] > level
        union = (a | b).sum()
        print("   {0} region: fixed {1} bins, adaptive {2} bins, overlap (IoU) {3:.2f}".format(
            label, a.sum(), b.sum(), (a & b).sum() / union if union else float("nan")))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("   (matplotlib not available: no plots)")
        return

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    extent = [bins[0][0], bins[0][-1], bins[1][0], bins[1][-1]]
    for ax, name in zip(axes[:2], ["fixed", "adaptive"]):
        img = np.where(np.isfinite(profiles[name]), profiles[name], np.nan).T
        im = ax.imshow(img, origin="lower", extent=extent, aspect="auto", vmin=-10, vmax=0, cmap="viridis")
        ax.contour(np.linspace(*extent[:2], n_bins), np.linspace(*extent[2:], n_bins), np.nan_to_num(img, nan=-99),
                   levels=[-3.09, -1.15], colors=["white", "red"], linewidths=1)
        ax.set(title="{0}: profile dlnL".format(name), xlabel=x, ylabel=y)
        fig.colorbar(im, ax=ax)
    ax = axes[2]
    hist_bins = np.logspace(np.log10(max(1., min(fixed["event_count"].min(), adaptive["event_count"].min()))),
                            np.log10(max(fixed["event_count"].max(), adaptive["event_count"].max())) + 0.05, 30)
    ax.hist(fixed["event_count"], bins=hist_bins, histtype="step", label="fixed")
    ax.hist(adaptive["event_count"], bins=hist_bins, histtype="step", label="adaptive")
    ax.set(xscale="log", xlabel="events generated per point", ylabel="points", title="MC events per point")
    ax.legend()
    fig.tight_layout()
    out = os.path.join(outdir, "adaptive_vs_fixed_{0}_{1}.png".format(x, y))
    fig.savefig(out, dpi=120)
    print("   plot written to " + out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fixed", help="hdf5 output of the fixed-N (log-only) scan")
    parser.add_argument("adaptive", help="hdf5 output of the adaptive scan")
    parser.add_argument("--group", default="/data")
    parser.add_argument("--collider", default="LHC_13TeV")
    parser.add_argument("--x", default="M1")
    parser.add_argument("--y", default="M2")
    parser.add_argument("--roi", type=float, default=5.99, help="delta lnL defining the region of interest")
    parser.add_argument("--threshold", type=float, default=15.0, help="adaptive_delta_lnL_threshold used in the scans")
    parser.add_argument("--outdir", default=".")
    args = parser.parse_args()

    params = sorted({args.x, args.y})
    fixed = load_scan(args.fixed, args.group, args.collider, params)
    adaptive = load_scan(args.adaptive, args.group, args.collider, params)

    summarise_cost("fixed", fixed)
    summarise_cost("adaptive", adaptive)
    speedup(fixed, adaptive)
    fidelity_from_log_only(fixed, args.roi, args.threshold)
    compare_profiles(fixed, adaptive, args.x, args.y, args.outdir)


if __name__ == "__main__":
    main()
