#!/usr/bin/env python3
"""
include_graph.py - Static include dependency analysis for GAMBIT.

Parses #include directives across the codebase without compiling anything,
then reports headers that are pulled in most frequently (prime candidates for
forward-declaration, include-guard checks, or precompiled headers), and flags
files with unusually deep or wide transitive include sets.

Usage:
    python3 scripts/build_profiling/include_graph.py [OPTIONS]

Options:
    --root DIR          Root of the GAMBIT source tree (default: auto-detected)
    --module MODULE     Restrict analysis to one module, e.g. DarkBit
    --top N             Show top N entries in each ranking (default: 30)
    --min-count N       Only report headers included at least N times (default: 5)
    --show-chains       Print the longest include chains for the top offenders
    --output FILE       Write JSON results to FILE for further processing
    --no-contrib        Exclude contrib/ headers from analysis (default: excluded)
    --include-contrib   Include contrib/ headers in analysis

Examples:
    # Quick overview across the whole codebase
    python3 scripts/build_profiling/include_graph.py

    # Focus on DarkBit, show top 20, include full chains
    python3 scripts/build_profiling/include_graph.py --module DarkBit --top 20 --show-chains

    # Save full results for later processing
    python3 scripts/build_profiling/include_graph.py --output results.json
"""

import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INCLUDE_RE = re.compile(r'^\s*#\s*include\s+["<]([^">]+)[">]')
SOURCE_EXTENSIONS = {'.cpp', '.cc', '.cxx', '.c', '.hpp', '.h', '.hh', '.hxx', '.tpp', '.ipp'}

GAMBIT_MODULES = [
    'Core', 'Utils', 'Elements', 'Models', 'Logs', 'Printers', 'ScannerBit',
    'DarkBit', 'ColliderBit', 'NeutrinoBit', 'DecayBit', 'FlavBit',
    'SpecBit', 'PrecisionBit', 'CosmoBit', 'ObjectivesBit',
    'ExampleBit_A', 'ExampleBit_B', 'Backends', 'gum',
]


def find_root() -> Path:
    """Walk up from this script to find the GAMBIT root (has CMakeLists.txt + Core/)."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / 'CMakeLists.txt').exists() and (parent / 'Core').exists():
            return parent
    sys.exit("ERROR: Could not locate GAMBIT root. Run from inside the repository or pass --root.")


def collect_source_files(root: Path, module: str | None, include_contrib: bool) -> list[Path]:
    files = []
    skip_dirs = {'build', '.git', '.github'}
    if not include_contrib:
        skip_dirs.add('contrib')

    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        # Prune directories we never want
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        # Restrict to module if requested
        rel = dp.relative_to(root)
        parts = rel.parts
        if module and parts and parts[0] != module:
            dirnames.clear()
            continue
        for fn in filenames:
            if Path(fn).suffix.lower() in SOURCE_EXTENSIONS:
                files.append(dp / fn)
    return files


def parse_includes(path: Path) -> list[str]:
    """Return list of raw include strings (exactly as written in the file)."""
    includes = []
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                m = INCLUDE_RE.match(line)
                if m:
                    includes.append(m.group(1))
    except OSError:
        pass
    return includes


def resolve_include(raw: str, including_file: Path, root: Path,
                    path_index: dict[str, list[Path]]) -> Path | None:
    """
    Try to resolve a raw include string to an actual file path.
    Strategy:
      1. Relative to the directory of the including file.
      2. Lookup in path_index by basename (handles gambit/Foo/bar.hpp style).
    """
    # 1. Relative to including file's directory
    candidate = including_file.parent / raw
    if candidate.exists():
        return candidate.resolve()

    # 2. Path index: exact suffix match
    basename = Path(raw).name
    if basename in path_index:
        candidates = path_index[basename]
        # Prefer files whose path ends with the raw include string
        for c in candidates:
            try:
                if str(c).endswith(raw.replace('/', os.sep)):
                    return c
            except Exception:
                pass
        # Fall back to first match
        return candidates[0]

    return None


def build_path_index(files: list[Path]) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = collections.defaultdict(list)
    for f in files:
        index[f.name].append(f)
    return index


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(files: list[Path], root: Path,
                include_contrib: bool) -> dict[str, list[str]]:
    """
    Returns adjacency list: file_str -> [included_file_str, ...]
    Keys are relative paths from root for readability.
    """
    all_files_set = set(files)
    path_index = build_path_index(files)

    graph: dict[str, list[str]] = {}
    unresolved_counts: dict[str, int] = collections.Counter()

    for f in files:
        raw_includes = parse_includes(f)
        resolved = []
        for raw in raw_includes:
            target = resolve_include(raw, f, root, path_index)
            if target and target in all_files_set:
                try:
                    resolved.append(str(target.relative_to(root)))
                except ValueError:
                    resolved.append(str(target))
            else:
                # Still record unresolved (system headers, etc.) for counting
                unresolved_counts[raw] += 1
        try:
            key = str(f.relative_to(root))
        except ValueError:
            key = str(f)
        graph[key] = resolved

    return graph, unresolved_counts


# ---------------------------------------------------------------------------
# Graph metrics
# ---------------------------------------------------------------------------

def compute_in_degree(graph: dict[str, list[str]]) -> dict[str, int]:
    """How many files directly include this file."""
    counts: dict[str, int] = collections.Counter()
    for includes in graph.values():
        for inc in includes:
            counts[inc] += 1
    return counts


def compute_transitive_includes(graph: dict[str, list[str]]) -> dict[str, set[str]]:
    """
    For each file, compute the set of all files it transitively includes.
    Uses memoised DFS. Cycles are handled by tracking the current stack.
    """
    memo: dict[str, set[str]] = {}

    def dfs(node: str, stack: set[str]) -> set[str]:
        if node in memo:
            return memo[node]
        if node in stack:  # cycle
            return set()
        stack.add(node)
        result: set[str] = set()
        for child in graph.get(node, []):
            result.add(child)
            result |= dfs(child, stack)
        stack.discard(node)
        memo[node] = result
        return result

    for node in graph:
        dfs(node, set())

    return memo


def find_longest_chain(graph: dict[str, list[str]], start: str) -> list[str]:
    """Return the longest include chain starting from `start`."""
    best: list[str] = [start]

    def dfs(node: str, path: list[str], visited: set[str]):
        nonlocal best
        if len(path) > len(best):
            best = path[:]
        for child in graph.get(node, []):
            if child not in visited:
                visited.add(child)
                path.append(child)
                dfs(child, path, visited)
                path.pop()
                visited.discard(child)

    dfs(start, [start], {start})
    return best


def module_of(path_str: str, modules: list[str]) -> str:
    parts = Path(path_str).parts
    if parts and parts[0] in modules:
        return parts[0]
    if parts and parts[0] == 'contrib':
        return 'contrib'
    return 'other'


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def fmt_size(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def print_section(title: str):
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def report(graph: dict[str, list[str]], root: Path,
           args: argparse.Namespace, unresolved: dict[str, int]):
    top_n = args.top
    min_count = args.min_count
    modules = GAMBIT_MODULES

    print_section("GAMBIT Include Graph Analysis")
    print(f"  Root: {root}")
    print(f"  Files analysed: {len(graph):,}")
    print(f"  Total direct include edges: {sum(len(v) for v in graph.values()):,}")

    # --- Direct include counts (in-degree) ---
    in_deg = compute_in_degree(graph)
    print_section(f"Top {top_n} most directly included headers (in-degree)")
    print(f"  {'Count':>6}  {'Module':<16}  File")
    print(f"  {'-'*6}  {'-'*16}  {'-'*46}")
    for path_str, count in sorted(in_deg.items(), key=lambda x: -x[1])[:top_n]:
        if count < min_count:
            break
        mod = module_of(path_str, modules)
        print(f"  {count:>6}  {mod:<16}  {path_str}")

    # --- Transitive include set size ---
    print_section(f"Top {top_n} source files with largest transitive include sets")
    trans = compute_transitive_includes(graph)
    # Only show .cpp / .cc (translation units), not headers
    tu_trans = {k: v for k, v in trans.items()
                if Path(k).suffix.lower() in {'.cpp', '.cc', '.cxx', '.c'}}
    print(f"  {'Trans.':>7}  {'Direct':>6}  {'Module':<16}  File")
    print(f"  {'-'*7}  {'-'*6}  {'-'*16}  {'-'*40}")
    for path_str, inc_set in sorted(tu_trans.items(), key=lambda x: -len(x[1]))[:top_n]:
        direct = len(graph.get(path_str, []))
        mod = module_of(path_str, modules)
        print(f"  {len(inc_set):>7}  {direct:>6}  {mod:<16}  {path_str}")

    # --- Headers with highest transitive fan-out (included and pulls in most) ---
    print_section(f"Top {top_n} headers by transitive fan-out (header pulls in the most)")
    hdr_trans = {k: v for k, v in trans.items()
                 if Path(k).suffix.lower() in {'.hpp', '.h', '.hh', '.hxx', '.tpp', '.ipp'}}
    print(f"  {'Trans.':>7}  {'Direct':>6}  {'In-deg':>6}  {'Module':<16}  File")
    print(f"  {'-'*7}  {'-'*6}  {'-'*6}  {'-'*16}  {'-'*40}")
    for path_str, inc_set in sorted(hdr_trans.items(), key=lambda x: -len(x[1]))[:top_n]:
        direct = len(graph.get(path_str, []))
        ind = in_deg.get(path_str, 0)
        mod = module_of(path_str, modules)
        print(f"  {len(inc_set):>7}  {direct:>6}  {ind:>6}  {mod:<16}  {path_str}")

    # --- Per-module summary ---
    print_section("Per-module include stats")
    mod_files: dict[str, list[str]] = collections.defaultdict(list)
    for f in graph:
        mod_files[module_of(f, modules)].append(f)

    print(f"  {'Module':<20}  {'Files':>6}  {'AvgDirect':>9}  {'AvgTrans':>9}  {'MaxTrans':>9}")
    print(f"  {'-'*20}  {'-'*6}  {'-'*9}  {'-'*9}  {'-'*9}")
    for mod in sorted(mod_files):
        files = mod_files[mod]
        directs = [len(graph.get(f, [])) for f in files]
        transs = [len(trans.get(f, set())) for f in files]
        avg_d = sum(directs) / len(directs) if directs else 0
        avg_t = sum(transs) / len(transs) if transs else 0
        max_t = max(transs) if transs else 0
        print(f"  {mod:<20}  {len(files):>6}  {avg_d:>9.1f}  {avg_t:>9.1f}  {max_t:>9}")

    # --- Duplication: headers included from many modules ---
    print_section("Cross-module header sharing (headers included by 3+ different modules)")
    hdr_modules: dict[str, set[str]] = collections.defaultdict(set)
    for src, includes in graph.items():
        src_mod = module_of(src, modules)
        for inc in includes:
            hdr_modules[inc].add(src_mod)
    shared = [(h, mods) for h, mods in hdr_modules.items() if len(mods) >= 3]
    shared.sort(key=lambda x: -len(x[1]))
    print(f"  {'Modules':>7}  File")
    print(f"  {'-'*7}  {'-'*60}")
    for hdr, mods in shared[:top_n]:
        print(f"  {len(mods):>7}  {hdr}  [{', '.join(sorted(mods)[:5])}{'...' if len(mods)>5 else ''}]")

    # --- Longest include chains ---
    if args.show_chains:
        print_section(f"Longest include chains (top {min(top_n, 10)})")
        # Find longest chain starting from each TU
        chains = []
        for f in list(tu_trans.keys())[:200]:  # limit for performance
            chain = find_longest_chain(graph, f)
            chains.append(chain)
        chains.sort(key=lambda c: -len(c))
        for chain in chains[:min(top_n, 10)]:
            print(f"\n  Chain length {len(chain)}:")
            for i, node in enumerate(chain):
                print(f"    {'  '*min(i,6)}-> {node}" if i else f"    {node}")

    # --- JSON output ---
    if args.output:
        results = {
            'files_analysed': len(graph),
            'in_degree': dict(sorted(in_deg.items(), key=lambda x: -x[1])[:500]),
            'transitive_size': {k: len(v) for k, v in
                                 sorted(trans.items(), key=lambda x: -len(x[1]))[:500]},
            'module_stats': {
                mod: {
                    'files': len(files),
                    'avg_direct': sum(len(graph.get(f, [])) for f in files) / max(len(files), 1),
                    'avg_transitive': sum(len(trans.get(f, set())) for f in files) / max(len(files), 1),
                }
                for mod, files in mod_files.items()
            },
        }
        out_path = Path(args.output)
        out_path.write_text(json.dumps(results, indent=2))
        print(f"\n  JSON results written to {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Static include dependency analysis for GAMBIT.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('Usage:')[0].strip(),
    )
    parser.add_argument('--root', default=None, help='GAMBIT source root directory')
    parser.add_argument('--module', default=None, help='Restrict to one module')
    parser.add_argument('--top', type=int, default=30, help='Show top N entries (default: 30)')
    parser.add_argument('--min-count', type=int, default=5,
                        help='Minimum direct-include count to report (default: 5)')
    parser.add_argument('--show-chains', action='store_true',
                        help='Print longest include chains')
    parser.add_argument('--output', default=None, help='Write JSON results to this file')
    parser.add_argument('--include-contrib', action='store_true',
                        help='Include contrib/ headers (default: excluded)')
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else find_root()

    t0 = time.time()
    print(f"Collecting source files under {root} ...")
    files = collect_source_files(root, args.module, args.include_contrib)
    print(f"  Found {len(files):,} files in {time.time()-t0:.1f}s")

    print("Building include graph (static parse, no compilation) ...")
    graph, unresolved = build_graph(files, root, args.include_contrib)
    print(f"  Done in {time.time()-t0:.1f}s")

    report(graph, root, args, unresolved)


if __name__ == '__main__':
    main()
