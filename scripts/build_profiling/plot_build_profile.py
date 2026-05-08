#!/usr/bin/env python3
"""
plot_build_profile.py - Generate visualisation plots from GAMBIT build profiling data.

Reads the JSON outputs from include_graph.py and preprocess_size.py and produces
a multi-panel PNG report covering:
  1. Total preprocessed size per module (bar chart)
  2. Average expansion ratio per module (bar chart)
  3. Average preprocessed size per TU per module (bar chart)
  4. Most-included headers (horizontal bar)
  5. Transitive include depth distribution per module (box plot)
  6. Top TUs by preprocessed size (horizontal bar)
  7. Include depth vs preprocessed size scatter (if both datasets available)
  8. Cross-module header sharing heatmap

Usage:
    python3 scripts/build_profiling/plot_build_profile.py [OPTIONS]

Options:
    --graph-json FILE      JSON from include_graph.py  (default: /tmp/include_graph.json)
    --pp-jsons GLOB        Glob of preprocess_size JSON files (default: /tmp/pp_*.json)
    --output FILE          Output PNG path (default: scripts/build_profiling/build_profile_report.png)
    --dpi N                Resolution (default: 150)
    --root DIR             GAMBIT root (auto-detected)

Examples:
    python3 scripts/build_profiling/plot_build_profile.py
    python3 scripts/build_profiling/plot_build_profile.py --output my_report.png --dpi 200
"""

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import numpy as np


# ── colour palette (one per module, consistent across panels) ─────────────────
MODULE_ORDER = [
    'ColliderBit', 'DarkBit', 'Models', 'ScannerBit', 'SpecBit', 'Printers',
    'Utils', 'Core', 'Elements', 'CosmoBit', 'NeutrinoBit', 'FlavBit',
    'DecayBit', 'Backends', 'Logs', 'gum', 'other',
]
PALETTE = plt.cm.tab20.colors + plt.cm.tab20b.colors
MODULE_COLOR = {mod: PALETTE[i % len(PALETTE)] for i, mod in enumerate(MODULE_ORDER)}


def module_color(name):
    return MODULE_COLOR.get(name, PALETTE[len(MODULE_ORDER) % len(PALETTE)])


def find_root():
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / 'CMakeLists.txt').exists() and (parent / 'Core').exists():
            return parent
    return Path('.').resolve()


def load_graph_json(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"  [warn] include_graph JSON not found: {path}")
        return {}


def load_pp_jsons(pattern: str) -> dict[str, list[dict]]:
    """Returns module -> list of file result dicts."""
    by_module: dict[str, list[dict]] = {}
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"  [warn] No preprocess_size JSON files matched: {pattern}")
        return {}
    for fpath in files:
        with open(fpath) as f:
            data = json.load(f)
        # Detect module from filename pp_<module>.json
        stem = Path(fpath).stem  # e.g. pp_darkbit
        mod_guess = stem.replace('pp_', '').replace('_', '')
        # Find actual module name (case-insensitive match)
        actual = mod_guess
        for m in MODULE_ORDER:
            if m.lower() == mod_guess.lower():
                actual = m
                break
        by_module[actual] = [r for r in data if 'error' not in r]
    return by_module


def bytes_to_mb(b):
    return b / 1_048_576


# ── Panel helpers ─────────────────────────────────────────────────────────────

def panel_total_pp_size(ax, by_module):
    """Bar chart: total preprocessed MB per module."""
    mods, totals = [], []
    for m in MODULE_ORDER:
        if m in by_module and by_module[m]:
            total = sum(r['pp_bytes'] for r in by_module[m])
            mods.append(m)
            totals.append(bytes_to_mb(total))
    if not mods:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        return

    colors = [module_color(m) for m in mods]
    bars = ax.bar(range(len(mods)), totals, color=colors, edgecolor='white', linewidth=0.5)
    ax.set_xticks(range(len(mods)))
    ax.set_xticklabels(mods, rotation=40, ha='right', fontsize=8)
    ax.set_ylabel('Total preprocessed (MB)')
    ax.set_title('Total preprocessed output per module', fontweight='bold')
    ax.yaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    for bar, val in zip(bars, totals):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f'{val:.0f}', ha='center', va='bottom', fontsize=7)


def panel_avg_ratio(ax, by_module):
    """Bar chart: average expansion ratio per module."""
    mods, ratios = [], []
    for m in MODULE_ORDER:
        if m in by_module and by_module[m]:
            rs = [r['expansion_ratio'] for r in by_module[m] if r['expansion_ratio'] > 0]
            if rs:
                mods.append(m)
                ratios.append(np.mean(rs))

    if not mods:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        return

    colors = [module_color(m) for m in mods]
    bars = ax.bar(range(len(mods)), ratios, color=colors, edgecolor='white', linewidth=0.5)
    ax.set_xticks(range(len(mods)))
    ax.set_xticklabels(mods, rotation=40, ha='right', fontsize=8)
    ax.set_ylabel('Average expansion ratio (×)')
    ax.set_title('Avg preprocessor expansion ratio\n(source bytes → preprocessed bytes)', fontweight='bold')
    ax.yaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    for bar, val in zip(bars, ratios):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 5,
                f'{val:.0f}×', ha='center', va='bottom', fontsize=7)


def panel_avg_pp_per_tu(ax, by_module):
    """Bar chart: average preprocessed MB per TU per module."""
    mods, avgs = [], []
    for m in MODULE_ORDER:
        if m in by_module and by_module[m]:
            rs = by_module[m]
            mods.append(m)
            avgs.append(bytes_to_mb(sum(r['pp_bytes'] for r in rs) / len(rs)))

    if not mods:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        return

    colors = [module_color(m) for m in mods]
    bars = ax.bar(range(len(mods)), avgs, color=colors, edgecolor='white', linewidth=0.5)
    ax.set_xticks(range(len(mods)))
    ax.set_xticklabels(mods, rotation=40, ha='right', fontsize=8)
    ax.set_ylabel('Avg preprocessed per TU (MB)')
    ax.set_title('Average preprocessed size per translation unit', fontweight='bold')
    ax.yaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)
    ax.axhline(np.mean(avgs), color='red', linewidth=1, linestyle='--', alpha=0.6,
               label=f'mean {np.mean(avgs):.1f} MB')
    ax.legend(fontsize=7)

    for bar, val in zip(bars, avgs):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                f'{val:.1f}', ha='center', va='bottom', fontsize=7)


def panel_most_included_headers(ax, graph_data):
    """Horizontal bar: top 20 most directly included headers."""
    in_deg = graph_data.get('in_degree', {})
    if not in_deg:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        return

    items = sorted(in_deg.items(), key=lambda x: -x[1])[:20]
    labels = [Path(p).name[:45] for p, _ in items]
    counts = [c for _, c in items]
    mods = []
    for p, _ in items:
        parts = Path(p).parts
        mod = next((pt for pt in parts if pt in MODULE_ORDER), 'other')
        mods.append(mod)

    colors = [module_color(m) for m in mods]
    y = range(len(labels))
    ax.barh(y, counts, color=colors, edgecolor='white', linewidth=0.4)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel('Direct include count (in-degree)')
    ax.set_title('Top 20 most directly included headers', fontweight='bold')
    ax.xaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    for i, (val, mod) in enumerate(zip(counts, mods)):
        ax.text(val + 1, i, str(val), va='center', fontsize=7)

    # Legend for modules
    seen = {}
    for m, c in zip(mods, colors):
        if m not in seen:
            seen[m] = c
    patches = [mpatches.Patch(color=c, label=m) for m, c in seen.items()]
    ax.legend(handles=patches, fontsize=6, loc='lower right')


def panel_transitive_depth_box(ax, graph_data):
    """Box plot: distribution of transitive include depths per module."""
    trans = graph_data.get('transitive_size', {})
    if not trans:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        return

    # Group by module
    mod_depths: dict[str, list[int]] = {}
    for path_str, depth in trans.items():
        parts = Path(path_str).parts
        mod = next((p for p in parts if p in MODULE_ORDER), 'other')
        mod_depths.setdefault(mod, []).append(depth)

    # Filter modules with enough data, sort by median
    filtered = [(m, d) for m, d in mod_depths.items() if len(d) >= 2]
    filtered.sort(key=lambda x: -np.median(x[1]))
    filtered = filtered[:14]

    if not filtered:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        return

    mods = [m for m, _ in filtered]
    data = [d for _, d in filtered]
    colors = [module_color(m) for m in mods]

    bp = ax.boxplot(data, patch_artist=True, vert=True,
                    medianprops=dict(color='black', linewidth=1.5),
                    flierprops=dict(marker='.', markersize=3, alpha=0.5),
                    whiskerprops=dict(linewidth=0.8),
                    capprops=dict(linewidth=0.8))
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_xticks(range(1, len(mods)+1))
    ax.set_xticklabels(mods, rotation=40, ha='right', fontsize=8)
    ax.set_ylabel('Transitive include depth')
    ax.set_title('Transitive include depth distribution per module', fontweight='bold')
    ax.yaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)


def panel_top_tu_by_pp(ax, by_module, top_n=25):
    """Horizontal bar: top N TUs by preprocessed size."""
    all_tus = []
    for mod, results in by_module.items():
        for r in results:
            all_tus.append((r['pp_bytes'], mod, Path(r['file']).name))
    all_tus.sort(key=lambda x: -x[0])
    all_tus = all_tus[:top_n]

    if not all_tus:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        return

    sizes = [bytes_to_mb(b) for b, _, _ in all_tus]
    labels = [f"{name[:38]}" for _, _, name in all_tus]
    colors = [module_color(m) for _, m, _ in all_tus]

    y = range(len(labels))
    ax.barh(y, sizes, color=colors, edgecolor='white', linewidth=0.4)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel('Preprocessed size (MB)')
    ax.set_title(f'Top {top_n} translation units by preprocessed size', fontweight='bold')
    ax.xaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    seen = {}
    for (_, mod, _), c in zip(all_tus, colors):
        if mod not in seen:
            seen[mod] = c
    patches = [mpatches.Patch(color=c, label=m) for m, c in seen.items()]
    ax.legend(handles=patches, fontsize=6, loc='lower right')


def panel_expansion_scatter(ax, by_module):
    """Scatter: original size vs preprocessed size, coloured by module."""
    for mod, results in by_module.items():
        orig = [bytes_to_mb(r['orig_bytes']) for r in results if r['orig_bytes'] > 0]
        pp   = [bytes_to_mb(r['pp_bytes'])   for r in results if r['orig_bytes'] > 0]
        if orig:
            ax.scatter(orig, pp, color=module_color(mod), label=mod,
                       alpha=0.65, s=20, edgecolors='none')

    all_orig = [bytes_to_mb(r['orig_bytes'])
                for rs in by_module.values() for r in rs if r['orig_bytes'] > 0]
    if all_orig:
        mx = max(all_orig)
        for ratio in (100, 500, 1000, 2000):
            xs = np.linspace(0, mx, 100)
            ax.plot(xs, xs * ratio, '--', linewidth=0.6, alpha=0.5,
                    label=f'{ratio}× line' if ratio in (100, 1000) else None)
            ax.text(mx * 0.98, mx * ratio * 0.98, f'{ratio}×',
                    fontsize=6, alpha=0.6, ha='right', va='top')

    ax.set_xlabel('Original source size (MB)')
    ax.set_ylabel('Preprocessed size (MB)')
    ax.set_title('Source size vs preprocessed size\n(diagonal lines = constant expansion ratios)',
                 fontweight='bold')
    ax.legend(fontsize=6, markerscale=1.2, ncol=2)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)


def panel_file_count_vs_total(ax, by_module):
    """Scatter: file count vs total preprocessed, sized by avg ratio."""
    mods, file_counts, totals, ratios = [], [], [], []
    for m in MODULE_ORDER:
        if m in by_module and by_module[m]:
            rs = by_module[m]
            mods.append(m)
            file_counts.append(len(rs))
            totals.append(bytes_to_mb(sum(r['pp_bytes'] for r in rs)))
            ratios.append(np.mean([r['expansion_ratio'] for r in rs if r['expansion_ratio'] > 0]))

    if not mods:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        return

    colors = [module_color(m) for m in mods]
    sizes = [max(30, r / 5) for r in ratios]
    sc = ax.scatter(file_counts, totals, c=colors, s=sizes, alpha=0.8, edgecolors='grey',
                    linewidths=0.5)

    for m, x, y in zip(mods, file_counts, totals):
        ax.annotate(m, (x, y), textcoords='offset points', xytext=(4, 4), fontsize=7)

    ax.set_xlabel('Number of translation units')
    ax.set_ylabel('Total preprocessed (MB)')
    ax.set_title('Module size: #TUs vs total preprocessed\n(bubble size ∝ avg expansion ratio)',
                 fontweight='bold')
    ax.xaxis.grid(True, alpha=0.3, linestyle='--')
    ax.yaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Plot GAMBIT build profile data.')
    parser.add_argument('--graph-json', default='/tmp/include_graph.json')
    parser.add_argument('--pp-jsons', default='/tmp/pp_*.json')
    parser.add_argument('--output', default=None)
    parser.add_argument('--dpi', type=int, default=150)
    parser.add_argument('--root', default=None)
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else find_root()
    out_path = args.output or str(root / 'scripts' / 'build_profiling' / 'build_profile_report.png')

    print('Loading data ...')
    graph_data = load_graph_json(args.graph_json)
    by_module = load_pp_jsons(args.pp_jsons)
    print(f'  include_graph data: {len(graph_data.get("in_degree", {}))} headers')
    print(f'  preprocess data:    {sum(len(v) for v in by_module.values())} TUs across'
          f' {len(by_module)} modules')

    # ── Layout ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(22, 28))
    fig.patch.set_facecolor('#f8f8f8')

    gs = gridspec.GridSpec(4, 2, figure=fig, hspace=0.52, wspace=0.32,
                           left=0.07, right=0.97, top=0.95, bottom=0.04)

    ax_total    = fig.add_subplot(gs[0, 0])
    ax_ratio    = fig.add_subplot(gs[0, 1])
    ax_avg_tu   = fig.add_subplot(gs[1, 0])
    ax_scatter2 = fig.add_subplot(gs[1, 1])
    ax_top_hdrs = fig.add_subplot(gs[2, 0])
    ax_box      = fig.add_subplot(gs[2, 1])
    ax_top_tu   = fig.add_subplot(gs[3, 0])
    ax_expscatt = fig.add_subplot(gs[3, 1])

    # ── Render panels ─────────────────────────────────────────────────────────
    print('Rendering panels ...')
    panel_total_pp_size(ax_total, by_module)
    panel_avg_ratio(ax_ratio, by_module)
    panel_avg_pp_per_tu(ax_avg_tu, by_module)
    panel_file_count_vs_total(ax_scatter2, by_module)
    panel_most_included_headers(ax_top_hdrs, graph_data)
    panel_transitive_depth_box(ax_box, graph_data)
    panel_top_tu_by_pp(ax_top_tu, by_module)
    panel_expansion_scatter(ax_expscatt, by_module)

    # ── Title & footer ────────────────────────────────────────────────────────
    fig.suptitle('GAMBIT Build Profiling Report\nPreprocessed source size & include graph analysis',
                 fontsize=15, fontweight='bold', y=0.975)

    total_mb = sum(
        sum(r['pp_bytes'] for r in rs)
        for rs in by_module.values()
    ) / 1_048_576
    n_tus = sum(len(v) for v in by_module.values())
    footer = (f'Analysed {n_tus} translation units | '
              f'Total preprocessed: {total_mb:.0f} MB | '
              f'Static include graph: {len(graph_data.get("in_degree", {}))} unique headers')
    fig.text(0.5, 0.005, footer, ha='center', fontsize=8, color='grey')

    print(f'Saving to {out_path} ...')
    fig.savefig(out_path, dpi=args.dpi, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f'Done → {out_path}')
    return out_path


if __name__ == '__main__':
    main()
