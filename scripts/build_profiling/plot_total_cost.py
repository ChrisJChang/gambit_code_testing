#!/usr/bin/env python3
"""
plot_total_cost.py - Plot total compile cost analysis from heavy_header_analysis.py output.

Generates a second detailed report focused on:
  1. Total compile cost per module (pp_size × in-degree, summed)
  2. Top headers by total compile cost (the true bottlenecks)
  3. Trivial vs structural header breakdown
  4. The include-depth chain for the highest-cost headers
  5. Comparison of standalone expansion vs total cost to highlight
     headers that are heavy AND frequently included

Usage:
    python3 scripts/build_profiling/plot_total_cost.py [OPTIONS]

Options:
    --heavy-json FILE   JSON from heavy_header_analysis.py (default: /tmp/heavy_all.json)
    --graph-json FILE   JSON from include_graph.py (default: /tmp/include_graph.json)
    --output FILE       Output PNG (default: scripts/build_profiling/total_cost_report.png)
    --dpi N             Resolution (default: 150)
"""

import argparse
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


MODULE_ORDER = [
    'Backends', 'Utils', 'ColliderBit', 'Elements', 'ScannerBit', 'Models',
    'Printers', 'DarkBit', 'SpecBit', 'Logs', 'Core', 'CosmoBit', 'gum',
    'FlavBit', 'DecayBit', 'NeutrinoBit', 'other',
]
PALETTE = list(plt.cm.tab20.colors) + list(plt.cm.tab20b.colors)
MODULE_COLOR = {mod: PALETTE[i % len(PALETTE)] for i, mod in enumerate(MODULE_ORDER)}


def module_color(name):
    return MODULE_COLOR.get(name, PALETTE[-1])


def find_root():
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / 'CMakeLists.txt').exists() and (parent / 'Core').exists():
            return parent
    return Path('.').resolve()


def module_of(path_str):
    parts = Path(path_str).parts
    for p in parts:
        if p in MODULE_ORDER:
            return p
    return 'other'


def fmt_mb(b):
    return b / 1_048_576


# ── Panels ───────────────────────────────────────────────────────────────────

def panel_total_cost_per_module(ax, by_mod_cost):
    mods = [m for m, _ in by_mod_cost if _ > 0]
    costs = [c / 1_048_576 for _, c in by_mod_cost if c > 0]
    colors = [module_color(m) for m in mods]

    bars = ax.barh(range(len(mods)), costs, color=colors, edgecolor='white', linewidth=0.4)
    ax.set_yticks(range(len(mods)))
    ax.set_yticklabels(mods, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel('Total compile cost (MB)  [= Σ standalone_size × in-degree]')
    ax.set_title('Total compile cost per module\n(size × frequency)', fontweight='bold')
    ax.xaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)
    for bar, val in zip(bars, costs):
        ax.text(val + 1, bar.get_y() + bar.get_height()/2,
                f'{val:.0f}', va='center', fontsize=7)


def panel_top_cost_headers(ax, records, top_n=30):
    top = sorted(records, key=lambda x: -x['total_cost_bytes'])[:top_n]
    top = [r for r in top if not r.get('trivial')][:top_n]
    labels = [Path(r['path']).name[:45] for r in top]
    costs = [r['total_cost_bytes'] / 1_048_576 for r in top]
    colors = [module_color(module_of(r['path'])) for r in top]

    y = range(len(labels))
    ax.barh(y, costs, color=colors, edgecolor='white', linewidth=0.3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel('Total compile cost (MB)')
    ax.set_title(f'Top {top_n} headers by total compile cost\n'
                 '(structural headers only — trivials excluded)', fontweight='bold')
    ax.xaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)
    seen = {}
    for r, c in zip(top, colors):
        m = module_of(r['path'])
        if m not in seen:
            seen[m] = c
    patches = [mpatches.Patch(color=c, label=m) for m, c in seen.items()]
    ax.legend(handles=patches, fontsize=6, loc='lower right')


def panel_standalone_vs_indegree(ax, records):
    """Scatter: standalone size vs in-degree, colour = module, size = total cost."""
    for r in records:
        if r.get('trivial'):
            continue
        mod = module_of(r['path'])
        x = r.get('in_degree', 0)
        y = r['pp_bytes'] / 1_048_576
        cost = r['total_cost_bytes'] / 1_048_576
        sz = max(5, min(300, cost * 0.4))
        ax.scatter(x, y, c=[module_color(mod)], s=sz, alpha=0.65, edgecolors='none')

    ax.set_xlabel('Include frequency (in-degree across codebase)')
    ax.set_ylabel('Standalone expansion size (MB)')
    ax.set_title('Header cost map\n(bubble size ∝ total compile cost)', fontweight='bold')

    # Highlight top offenders
    top10 = sorted([r for r in records if not r.get('trivial')],
                   key=lambda x: -x['total_cost_bytes'])[:10]
    for r in top10:
        x = r.get('in_degree', 0)
        y = r['pp_bytes'] / 1_048_576
        ax.annotate(Path(r['path']).name[:28],
                    (x, y), textcoords='offset points', xytext=(4, 3), fontsize=6,
                    arrowprops=dict(arrowstyle='->', color='grey', lw=0.5))

    # iso-cost lines
    xlim = ax.get_xlim() or (0, 100)
    x_arr = np.linspace(0.5, max(xlim[1], 100), 200)
    for cost_mb in (50, 100, 200):
        y_arr = cost_mb / x_arr
        valid = y_arr < 4
        ax.plot(x_arr[valid], y_arr[valid], '--', linewidth=0.6, alpha=0.4,
                label=f'{cost_mb} MB total' if cost_mb == 100 else None)
        idx = np.searchsorted(x_arr, min(x_arr[-1], 50))
        if idx < len(x_arr) and y_arr[idx] < 4:
            ax.text(x_arr[idx], y_arr[idx], f'{cost_mb}MB', fontsize=6, alpha=0.5)

    ax.set_xlim(left=0)
    ax.set_ylim(0, 4)
    ax.xaxis.grid(True, alpha=0.3, linestyle='--')
    ax.yaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    seen = {}
    for r in records:
        m = module_of(r['path'])
        if m not in seen:
            seen[m] = module_color(m)
    patches = [mpatches.Patch(color=c, label=m) for m, c in list(seen.items())[:10]]
    ax.legend(handles=patches, fontsize=6, ncol=2, loc='upper right')


def panel_trivial_breakdown(ax, records):
    """Bar chart showing trivial vs structural headers per module and their costs."""
    by_mod: dict[str, dict] = {}
    for r in records:
        m = module_of(r['path'])
        if m not in by_mod:
            by_mod[m] = {'structural_cost': 0, 'trivial_cost': 0,
                          'structural_n': 0, 'trivial_n': 0}
        if r.get('trivial'):
            by_mod[m]['trivial_cost'] += r['total_cost_bytes'] / 1_048_576
            by_mod[m]['trivial_n'] += 1
        else:
            by_mod[m]['structural_cost'] += r['total_cost_bytes'] / 1_048_576
            by_mod[m]['structural_n'] += 1

    # Only show modules with meaningful cost
    rows = [(m, d) for m, d in by_mod.items()
            if d['structural_cost'] + d['trivial_cost'] > 5]
    rows.sort(key=lambda x: -(x[1]['structural_cost'] + x[1]['trivial_cost']))

    mods = [m for m, _ in rows]
    struct_costs = [d['structural_cost'] for _, d in rows]
    trivial_costs = [d['trivial_cost'] for _, d in rows]
    x = range(len(mods))

    ax.bar(x, struct_costs, label='Structural headers', color='steelblue', alpha=0.8)
    ax.bar(x, trivial_costs, bottom=struct_costs, label='Trivial headers\n(#include-only wrappers)',
           color='lightcoral', alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(mods, rotation=40, ha='right', fontsize=8)
    ax.set_ylabel('Total compile cost (MB)')
    ax.set_title('Structural vs trivial (wrapper) header cost per module',
                 fontweight='bold')
    ax.legend(fontsize=8)
    ax.yaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)


def panel_cost_per_header_scatter(ax, records):
    """Standalone pp size histogram — shows the bimodal 'floor' distribution."""
    pp_sizes = [r['pp_bytes'] / 1_048_576 for r in records
                if not r.get('trivial') and r['pp_bytes'] > 0]
    ax.hist(pp_sizes, bins=40, color='steelblue', alpha=0.75, edgecolor='white')
    ax.axvline(np.median(pp_sizes), color='red', linewidth=1.5, linestyle='--',
               label=f'Median: {np.median(pp_sizes):.2f} MB')
    ax.axvline(np.mean(pp_sizes), color='orange', linewidth=1.5, linestyle='-.',
               label=f'Mean: {np.mean(pp_sizes):.2f} MB')
    ax.set_xlabel('Standalone preprocessed size (MB)')
    ax.set_ylabel('Number of headers')
    ax.set_title('Distribution of standalone header expansion sizes\n'
                 '(structural headers only)', fontweight='bold')
    ax.legend(fontsize=8)
    ax.yaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)

    # Annotate the "floor" cluster
    ax.text(0.05, 0.85,
            'The peak near 2-2.5 MB is the\n"infrastructure floor" — headers\n'
            'that all pull in util_types.hpp\n→ variadic_functions.hpp\n→ 13 STL containers',
            transform=ax.transAxes, fontsize=7, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))


def panel_root_cause_waterfall(ax, _records=None):
    """Bar chart showing the cumulative cost of the util_types.hpp include chain."""
    # Data from the investigation measurements
    chain = [
        ('variadic_functions\n(13 STL headers)', 1610, '#e74c3c'),
        ('standalone_error\n_handlers', 961, '#e67e22'),
        ('local_info', 652, '#f1c40f'),
        ('exceptions\n(util_macros+log_tags)', 675, '#2ecc71'),
        ('Direct STL in\nutil_types itself', 300, '#3498db'),
        (' Overlap / dedup\n(approx.)', -1000, '#95a5a6'),
    ]
    labels = [c[0] for c in chain]
    values = [c[1] for c in chain]
    colors = [c[2] for c in chain]
    baseline = 0
    bottoms = []
    for v in values:
        bottoms.append(baseline)
        if v > 0:
            baseline += v

    ax.bar(range(len(labels)), [abs(v) for v in values],
           bottom=[b if v > 0 else b + v for b, v in zip(bottoms, values)],
           color=colors, edgecolor='white', alpha=0.85)
    ax.axhline(2170, color='black', linewidth=2, linestyle='--',
               label='Actual util_types.hpp\nstandalone: 2170 KB')
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylabel('Preprocessed KB')
    ax.set_title('util_types.hpp expansion breakdown\n'
                 '(root of the ~2 MB infrastructure floor)', fontweight='bold')
    ax.legend(fontsize=7)
    ax.yaxis.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)


def panel_top_cost_table(ax, records, top_n=20):
    """Text table of top headers by total cost with actionability notes."""
    ax.axis('off')
    top = sorted([r for r in records if not r.get('trivial')],
                 key=lambda x: -x['total_cost_bytes'])[:top_n]

    headers = ['Header', 'Module', 'Standalone', 'In-degree', 'Total Cost', 'Action']
    actions = {
        'util_functions.hpp': 'Split: fwd decls vs definitions',
        'util_types.hpp':     'Remove variadic_functions.hpp dep',
        'model_macros.hpp':   'Conditional heavy include',
        'DarkBit_rollcall.hpp': 'Split into sub-rollcalls',
        'DarkBit_utils.hpp':  'Forward-declare where possible',
        'functors.hpp':       'Needs safety_bucket refactor',
        'safety_bucket.hpp':  'Circular with functors.hpp',
        'gambit_module_headers.hpp': 'Umbrella - investigate chain',
    }

    table_data = []
    for r in top:
        name = Path(r['path']).name
        mod = module_of(r['path'])
        standalone = f"{r['pp_bytes']/1_048_576:.2f} MB"
        indeg = str(r.get('in_degree', 0))
        total = f"{r['total_cost_bytes']/1_048_576:.0f} MB"
        action = actions.get(name, '—')
        table_data.append([name[:28], mod[:10], standalone, indeg, total, action[:30]])

    t = ax.table(cellText=table_data, colLabels=headers,
                 cellLoc='left', loc='center', bbox=[0, 0, 1, 1])
    t.auto_set_font_size(False)
    t.set_fontsize(6.5)
    # Header row style
    for j in range(len(headers)):
        t[0, j].set_facecolor('#2c3e50')
        t[0, j].set_text_props(color='white', fontweight='bold')
    # Alternate row colors
    for i in range(1, len(table_data) + 1):
        bg = '#ecf0f1' if i % 2 == 0 else 'white'
        for j in range(len(headers)):
            t[i, j].set_facecolor(bg)

    ax.set_title('Top structural headers by total compile cost with actionability',
                 fontweight='bold', pad=15)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--heavy-json', default='/tmp/heavy_all.json')
    parser.add_argument('--graph-json', default='/tmp/include_graph.json')
    parser.add_argument('--output', default=None)
    parser.add_argument('--dpi', type=int, default=150)
    args = parser.parse_args()

    root = find_root()
    out_path = args.output or str(root / 'scripts' / 'build_profiling' / 'total_cost_report.png')

    with open(args.heavy_json) as f:
        records = json.load(f)
    print(f"Loaded {len(records)} header records")

    # Per-module total cost
    by_mod: dict[str, float] = {}
    for r in records:
        m = module_of(r['path'])
        by_mod[m] = by_mod.get(m, 0) + r['total_cost_bytes']
    by_mod_cost = sorted(by_mod.items(), key=lambda x: -x[1])

    fig = plt.figure(figsize=(22, 30))
    fig.patch.set_facecolor('#f8f8f8')
    gs = gridspec.GridSpec(4, 2, figure=fig, hspace=0.50, wspace=0.35,
                           left=0.06, right=0.97, top=0.94, bottom=0.03)

    ax0 = fig.add_subplot(gs[0, 0])
    ax1 = fig.add_subplot(gs[0, 1])
    ax2 = fig.add_subplot(gs[1, 0])
    ax3 = fig.add_subplot(gs[1, 1])
    ax4 = fig.add_subplot(gs[2, 0])
    ax5 = fig.add_subplot(gs[2, 1])
    ax6 = fig.add_subplot(gs[3, :])

    panel_total_cost_per_module(ax0, by_mod_cost)
    panel_top_cost_headers(ax1, records, top_n=25)
    panel_standalone_vs_indegree(ax2, records)
    panel_trivial_breakdown(ax3, records)
    panel_cost_per_header_scatter(ax4, records)
    panel_root_cause_waterfall(ax5, records)
    panel_top_cost_table(ax6, records, top_n=18)

    fig.suptitle('GAMBIT Total Compile Cost Analysis\n'
                 'True bottleneck: headers ranked by (standalone size × include frequency)',
                 fontsize=14, fontweight='bold', y=0.975)

    total_cost = sum(r['total_cost_bytes'] for r in records) / 1_048_576
    n_structural = sum(1 for r in records if not r.get('trivial'))
    n_trivial = sum(1 for r in records if r.get('trivial'))
    footer = (f'Total estimated compile cost (headers only): {total_cost:.0f} MB  |  '
              f'{n_structural} structural headers  |  {n_trivial} trivial (wrapper/undef) headers')
    fig.text(0.5, 0.005, footer, ha='center', fontsize=8, color='grey')

    print(f'Saving → {out_path}')
    fig.savefig(out_path, dpi=args.dpi, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print('Done')


if __name__ == '__main__':
    main()
