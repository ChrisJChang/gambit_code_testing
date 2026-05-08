#!/usr/bin/env python3
"""
heavy_header_analysis.py - Measure the standalone preprocessed expansion size of
individual headers to rank true compile-time cost.

The include graph tells us which headers are *included most*, but a header
included 300 times with 10 lines costs nothing while one included 5 times with
50,000 preprocessed lines is catastrophic.  This script runs the preprocessor
on each header IN ISOLATION (as if it were a minimal .cpp that just includes it)
and records its standalone expansion size.  Combining that with include-count
gives a *total compile cost* estimate per header.

It then cross-references with the include graph to identify:
  - Headers with high total cost (heavy AND frequently included)
  - Headers with high expansion but low include count (might be worth splitting)
  - "Trivial" headers (only #undef / #define, near-zero expansion) that are safe
    to deprioritise even if included very frequently

Usage:
    python3 scripts/build_profiling/heavy_header_analysis.py [OPTIONS]

Options:
    --root DIR          GAMBIT source root (auto-detected)
    --compiler CMD      C++ compiler to use (default: clang++)
    --graph-json FILE   JSON from include_graph.py (default: /tmp/include_graph.json)
    --jobs N            Parallel workers (default: half CPU count)
    --top N             Show top N entries (default: 40)
    --module MODULE     Restrict header scan to one module
    --min-kb N          Minimum preprocessed KB to report (default: 50)
    --output FILE       Write JSON results to FILE
    --include-contrib   Include contrib/ headers (default: excluded)

Examples:
    # Full analysis (uses cached include_graph.json)
    python3 scripts/build_profiling/heavy_header_analysis.py

    # Focus on DarkBit and Core headers only
    python3 scripts/build_profiling/heavy_header_analysis.py --module DarkBit

    # Save for later plotting
    python3 scripts/build_profiling/heavy_header_analysis.py --output /tmp/heavy_headers.json
"""

import argparse
import collections
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


GAMBIT_MODULES = [
    'Core', 'Utils', 'Elements', 'Models', 'Logs', 'Printers', 'ScannerBit',
    'DarkBit', 'ColliderBit', 'NeutrinoBit', 'DecayBit', 'FlavBit',
    'SpecBit', 'PrecisionBit', 'CosmoBit', 'ObjectivesBit',
    'ExampleBit_A', 'ExampleBit_B', 'Backends', 'gum',
]

HEADER_EXTENSIONS = {'.hpp', '.h', '.hh', '.hxx', '.tpp', '.ipp'}


def find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / 'CMakeLists.txt').exists() and (parent / 'Core').exists():
            return parent
    sys.exit("Cannot find GAMBIT root.")


def default_flags(root: Path) -> list[str]:
    flags = ['-std=c++17']
    for mod in GAMBIT_MODULES:
        inc = root / mod / 'include'
        if inc.exists():
            flags += [f'-I{inc}']
    flags += [f'-I{root}']
    yaml_inc = root / 'contrib' / 'yaml-cpp-0.6.2' / 'include'
    if yaml_inc.exists():
        flags += [f'-I{yaml_inc}']
    return flags


def collect_headers(root: Path, module: str | None, include_contrib: bool) -> list[Path]:
    headers = []
    skip_dirs = {'build', '.git', '.github'}
    if not include_contrib:
        skip_dirs.add('contrib')
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        rel = dp.relative_to(root)
        parts = rel.parts
        if module and parts and parts[0] != module:
            dirnames.clear()
            continue
        for fn in filenames:
            if Path(fn).suffix.lower() in HEADER_EXTENSIONS:
                headers.append(dp / fn)
    return headers


def classify_header(path: Path) -> str:
    """Classify a header as 'trivial' (only undefs/defines) or 'structural'."""
    import re
    substantive_re = re.compile(
        r'^\s*(?!#\s*(?:undef|define|ifndef|ifdef|endif|pragma\s+once|if\s+0))'
        r'(?!//|/\*)(?!\s*$).+',
        re.MULTILINE,
    )
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
        # Strip comments and check for substantive content
        lines = [l for l in text.splitlines()
                 if l.strip() and not l.strip().startswith('//')]
        non_trivial = [
            l for l in lines
            if not any(l.strip().startswith(p) for p in
                       ('#undef ', '#define ', '#ifndef ', '#ifdef ', '#endif',
                        '#if ', '#else', '#pragma', '/*', '*/', '*', '#include'))
        ]
        if len(non_trivial) <= 3:
            return 'trivial'
    except OSError:
        pass
    return 'structural'


def preprocess_header(args_tuple) -> dict:
    """Measure standalone expansion of a single header file."""
    header_path, compiler, flags = args_tuple
    # Write a minimal wrapper translation unit
    wrapper = f'#include "{header_path}"\n'
    with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as tf:
        tf.write(wrapper)
        tmp = tf.name
    try:
        result = subprocess.run(
            [compiler, '-E', '-w'] + flags + [tmp],
            capture_output=True, timeout=60,
        )
        pp_bytes = len(result.stdout)
        pp_lines = result.stdout.count(b'\n')
        had_error = result.returncode != 0
    except subprocess.TimeoutExpired:
        return {'path': str(header_path), 'error': 'timeout'}
    except Exception as e:
        return {'path': str(header_path), 'error': str(e)}
    finally:
        os.unlink(tmp)

    orig_bytes = header_path.stat().st_size
    return {
        'path': str(header_path),
        'orig_bytes': orig_bytes,
        'pp_bytes': pp_bytes,
        'pp_lines': pp_lines,
        'had_error': had_error,
        'expansion_ratio': pp_bytes / orig_bytes if orig_bytes else 0,
    }


def module_of(path_str: str) -> str:
    parts = Path(path_str).parts
    for p in parts:
        if p in GAMBIT_MODULES:
            return p
    return 'other'


def fmt_bytes(n: int) -> str:
    if n >= 1_048_576:
        return f"{n/1_048_576:.2f} MB"
    if n >= 1_024:
        return f"{n/1_024:.1f} KB"
    return f"{n} B"


def print_section(title: str):
    print()
    print('=' * 72)
    print(f'  {title}')
    print('=' * 72)


def main():
    parser = argparse.ArgumentParser(
        description='Measure standalone expansion size of GAMBIT headers.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--root', default=None)
    parser.add_argument('--compiler', default='clang++')
    parser.add_argument('--graph-json', default='/tmp/include_graph.json')
    parser.add_argument('--jobs', type=int, default=max(1, os.cpu_count() // 2))
    parser.add_argument('--top', type=int, default=40)
    parser.add_argument('--module', default=None)
    parser.add_argument('--min-kb', type=float, default=50.0)
    parser.add_argument('--output', default=None)
    parser.add_argument('--include-contrib', action='store_true')
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else find_root()
    min_bytes = int(args.min_kb * 1024)

    # Load include graph for frequency data
    graph_data = {}
    in_degree: dict[str, int] = {}
    try:
        with open(args.graph_json) as f:
            graph_data = json.load(f)
        in_degree = graph_data.get('in_degree', {})
        print(f"Loaded include graph: {len(in_degree)} header frequencies")
    except FileNotFoundError:
        print(f"[warn] No include graph JSON at {args.graph_json}; run include_graph.py first")

    print(f"Collecting headers under {root} ...")
    headers = collect_headers(root, args.module, args.include_contrib)
    print(f"  Found {len(headers)} header files")

    flags = default_flags(root)
    tasks = [(h, args.compiler, flags) for h in headers]

    print(f"Preprocessing {len(tasks)} headers with {args.jobs} workers ...")
    print("  (Each header is preprocessed as a standalone unit)")
    t0 = time.time()
    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futures = {ex.submit(preprocess_header, t): t for t in tasks}
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
            done += 1
            if done % 100 == 0 or done == len(tasks):
                elapsed = time.time() - t0
                rate = done / elapsed
                eta = (len(tasks) - done) / rate if rate else 0
                print(f"  {done}/{len(tasks)}  {elapsed:.0f}s  ETA {eta:.0f}s",
                      end='\r', flush=True)
    print()
    elapsed = time.time() - t0
    print(f"Done in {elapsed:.1f}s")

    ok = [r for r in results if 'error' not in r and r.get('pp_bytes', 0) > 0]
    errors = [r for r in results if 'error' in r]
    print(f"  {len(ok)} ok, {len(errors)} errors/timeouts")

    # Classify trivial vs structural
    trivial_set = set()
    for r in ok:
        try:
            rel = str(Path(r['path']).relative_to(root))
        except ValueError:
            rel = r['path']
        if classify_header(Path(r['path'])) == 'trivial':
            trivial_set.add(rel)

    # --- Compute total compile cost = pp_bytes × in-degree ---
    for r in ok:
        try:
            rel = str(Path(r['path']).relative_to(root))
        except ValueError:
            rel = r['path']
        r['rel_path'] = rel
        r['in_degree'] = in_degree.get(rel, 0)
        r['total_cost_bytes'] = r['pp_bytes'] * max(r['in_degree'], 1)
        r['trivial'] = rel in trivial_set

    # Sort by standalone expansion for initial report
    ok.sort(key=lambda x: -x['pp_bytes'])

    print_section(f"Top {args.top} headers by STANDALONE expansion size")
    print("  Standalone = preprocessed bytes when included as only header in a TU")
    print()
    print(f"  {'PP size':>9}  {'Orig':>7}  {'Ratio':>6}  {'Triv':>4}  {'Module':<16}  Header")
    print(f"  {'-'*9}  {'-'*7}  {'-'*6}  {'-'*4}  {'-'*16}  {'-'*42}")
    shown = 0
    for r in ok:
        if r['pp_bytes'] < min_bytes:
            break
        if shown >= args.top:
            break
        mod = module_of(r['rel_path'])
        triv = 'YES' if r['trivial'] else ''
        print(f"  {fmt_bytes(r['pp_bytes']):>9}  {fmt_bytes(r['orig_bytes']):>7}  "
              f"{r['expansion_ratio']:>5.0f}×  {triv:>4}  {mod:<16}  "
              f"{Path(r['rel_path']).name[:42]}")
        shown += 1

    print_section(f"Top {args.top} headers by TOTAL COMPILE COST (size × include-count)")
    print("  This is the real metric: how much preprocessor work does each header")
    print("  collectively impose across the entire build.")
    print()
    print(f"  {'TotalCost':>10}  {'InDeg':>5}  {'PP size':>9}  {'Triv':>4}  {'Module':<16}  Header")
    print(f"  {'-'*10}  {'-'*5}  {'-'*9}  {'-'*4}  {'-'*16}  {'-'*42}")
    by_cost = sorted(ok, key=lambda x: -x['total_cost_bytes'])
    shown = 0
    for r in by_cost:
        if r['total_cost_bytes'] < min_bytes:
            break
        if shown >= args.top:
            break
        mod = module_of(r['rel_path'])
        triv = 'YES' if r['trivial'] else ''
        cost_str = fmt_bytes(r['total_cost_bytes'])
        print(f"  {cost_str:>10}  {r['in_degree']:>5}  "
              f"{fmt_bytes(r['pp_bytes']):>9}  {triv:>4}  {mod:<16}  "
              f"{Path(r['rel_path']).name[:42]}")
        shown += 1

    print_section("Trivial headers with high include counts (safe to deprioritise)")
    print("  These are included many times but have near-zero parse cost.")
    print("  High include-count does NOT mean high compile-time cost for these.")
    print()
    trivial_high = [r for r in ok if r['trivial'] and r['in_degree'] >= 5]
    trivial_high.sort(key=lambda x: -x['in_degree'])
    print(f"  {'InDeg':>5}  {'PP size':>9}  {'Module':<16}  Header")
    print(f"  {'-'*5}  {'-'*9}  {'-'*16}  {'-'*42}")
    for r in trivial_high[:20]:
        mod = module_of(r['rel_path'])
        print(f"  {r['in_degree']:>5}  {fmt_bytes(r['pp_bytes']):>9}  {mod:<16}  "
              f"{Path(r['rel_path']).name[:42]}")

    print_section("Per-module: total standalone expansion of all headers")
    by_mod: dict[str, list[dict]] = collections.defaultdict(list)
    for r in ok:
        by_mod[module_of(r['rel_path'])].append(r)
    mod_rows = []
    for mod, rs in by_mod.items():
        structural = [r for r in rs if not r['trivial']]
        total_pp = sum(r['pp_bytes'] for r in structural)
        total_cost = sum(r['total_cost_bytes'] for r in structural)
        mod_rows.append((mod, len(structural), total_pp, total_cost))
    mod_rows.sort(key=lambda x: -x[3])
    print(f"  {'Module':<20}  {'Hdrs':>5}  {'TotalPP':>10}  {'TotalCost':>12}")
    print(f"  {'-'*20}  {'-'*5}  {'-'*10}  {'-'*12}")
    for mod, count, total_pp, total_cost in mod_rows:
        print(f"  {mod:<20}  {count:>5}  {fmt_bytes(total_pp):>10}  {fmt_bytes(total_cost):>12}")

    if args.output:
        out_data = [
            {
                'path': r['rel_path'],
                'pp_bytes': r['pp_bytes'],
                'orig_bytes': r['orig_bytes'],
                'in_degree': r['in_degree'],
                'total_cost_bytes': r['total_cost_bytes'],
                'trivial': r['trivial'],
                'had_error': r.get('had_error', False),
            }
            for r in ok
        ]
        Path(args.output).write_text(json.dumps(out_data, indent=2))
        print(f"\nJSON results written to {args.output}")


if __name__ == '__main__':
    main()
