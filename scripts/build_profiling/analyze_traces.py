#!/usr/bin/env python3
"""
analyze_traces.py - Parse clang -ftime-trace JSON flamegraphs for GAMBIT.

clang++ -ftime-trace produces a JSON file per translation unit containing a
Chrome-trace-format flamegraph.  This script aggregates those files and shows:

  - Which source files take the longest total time to compile
  - How time is split between: parsing headers, instantiating templates,
    codegen, and optimisation
  - Which C++ template instantiations consume the most cumulative time
    across all translation units (the single biggest lever for C++ compile time)
  - Which individual headers dominate parse time

Requires: clang++ >= 9, -ftime-trace flag (set automatically by
          build_time_profile.sh when using clang).

Usage:
    python3 scripts/build_profiling/analyze_traces.py [OPTIONS]

Options:
    --traces-dir DIR    Directory containing *.json trace files
                        (default: build_profile/profile_logs/traces/)
    --build-dir DIR     CMake build directory (alternative to --traces-dir;
                        script will search recursively for *.json traces)
    --top N             Show top N entries per category (default: 30)
    --module MODULE     Filter to traces for one GAMBIT module
    --min-ms N          Minimum milliseconds to include an event (default: 10)
    --output FILE       Write JSON summary to FILE
    --flamegraph FILE   Write combined Chrome trace JSON to FILE (open in
                        chrome://tracing or Perfetto)

Examples:
    # After running build_time_profile.sh with clang:
    python3 scripts/build_profiling/analyze_traces.py

    # Custom trace directory:
    python3 scripts/build_profiling/analyze_traces.py --traces-dir my_traces/

    # Save combined flamegraph for browser inspection:
    python3 scripts/build_profiling/analyze_traces.py --flamegraph combined.json
"""

import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path


GAMBIT_MODULES = [
    'Core', 'Utils', 'Elements', 'Models', 'Logs', 'Printers', 'ScannerBit',
    'DarkBit', 'ColliderBit', 'NeutrinoBit', 'DecayBit', 'FlavBit',
    'SpecBit', 'PrecisionBit', 'CosmoBit', 'ObjectivesBit',
    'ExampleBit_A', 'ExampleBit_B', 'Backends', 'gum',
]

# clang trace event names we care about
PARSE_EVENTS = {'Frontend', 'ParseDeclarationOrFunctionDefinition',
                'ParseClass', 'ParseTemplate', 'ParseFunctionDefinition'}
INSTANTIATION_EVENTS = {'InstantiateClass', 'InstantiateFunction',
                         'InstantiateVariable', 'InstantiateConcept',
                         'TemplateInstantiation'}
CODEGEN_EVENTS = {'CodeGen Function', 'CodeGenPasses', 'IRGeneration',
                  'RunLoopPasses', 'RunCodegenPasses'}
INCLUDE_EVENTS = {'Source', 'ParseFile'}
OPTIMIZE_EVENTS = {'OptFunction', 'PerFunctionPasses', 'PerModulePasses',
                   'RunPass', 'OptModule'}

ALL_CATEGORIES = {
    'parse': PARSE_EVENTS,
    'instantiation': INSTANTIATION_EVENTS,
    'codegen': CODEGEN_EVENTS,
    'optimize': OPTIMIZE_EVENTS,
}


def find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / 'CMakeLists.txt').exists() and (parent / 'Core').exists():
            return parent
    return Path('.')


def find_trace_files(search_path: Path, module: str | None) -> list[Path]:
    traces = []
    for dirpath, _, filenames in os.walk(search_path):
        for fn in filenames:
            if fn.endswith('.json'):
                p = Path(dirpath) / fn
                # Quick check: clang traces start with {"traceEvents"
                try:
                    with open(p) as fh:
                        peek = fh.read(30)
                    if 'traceEvents' in peek:
                        traces.append(p)
                except OSError:
                    pass
    if module:
        traces = [t for t in traces if module.lower() in str(t).lower()]
    return traces


def load_trace(path: Path) -> tuple[str, list[dict]]:
    """Load one trace file, return (source_file_name, events)."""
    with open(path) as fh:
        data = json.load(fh)
    events = data.get('traceEvents', [])
    # The first 'Total ExecuteCompiler' or 'Source' event usually has the file
    src_name = path.stem  # filename without .json
    for ev in events:
        if ev.get('name') == 'Total ExecuteCompiler' and 'args' in ev:
            detail = ev['args'].get('detail', '')
            if detail:
                src_name = detail
                break
    return src_name, events


def us_to_ms(us: float) -> float:
    return us / 1000.0


def categorise_event(name: str) -> str | None:
    for cat, names in ALL_CATEGORIES.items():
        if name in names:
            return cat
    return None


def module_of(path_str: str) -> str:
    parts = Path(path_str).parts
    for p in parts:
        if p in GAMBIT_MODULES:
            return p
    return 'other'


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

class TraceStats:
    def __init__(self):
        self.total_ms: float = 0
        self.by_category: dict[str, float] = collections.defaultdict(float)
        # template instantiation: name -> cumulative ms
        self.instantiations: dict[str, float] = collections.defaultdict(float)
        # header parse: file -> ms
        self.header_parse: dict[str, float] = collections.defaultdict(float)
        # function codegen: name -> ms
        self.codegen_funcs: dict[str, float] = collections.defaultdict(float)


def analyse_trace(src_name: str, events: list[dict]) -> TraceStats:
    stats = TraceStats()
    for ev in events:
        if ev.get('ph') not in ('X', 'B'):
            continue
        name = ev.get('name', '')
        dur = ev.get('dur', 0)  # microseconds
        ms = us_to_ms(dur)

        if name == 'Total ExecuteCompiler':
            stats.total_ms = ms
            continue

        cat = categorise_event(name)
        if cat:
            stats.by_category[cat] += ms

        detail = ev.get('args', {}).get('detail', '')

        if name in INSTANTIATION_EVENTS and detail:
            stats.instantiations[detail] += ms

        if name in ('Source', 'ParseFile') and detail:
            stats.header_parse[detail] += ms

        if name in ('CodeGen Function',) and detail:
            stats.codegen_funcs[detail] += ms

    return stats


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_section(title: str):
    print()
    print('=' * 72)
    print(f'  {title}')
    print('=' * 72)


def fmt_ms(ms: float) -> str:
    if ms >= 60_000:
        return f"{ms/60_000:.1f}m"
    if ms >= 1_000:
        return f"{ms/1_000:.1f}s"
    return f"{ms:.0f}ms"


def report(per_file: dict[str, TraceStats], top_n: int, min_ms: float):

    print_section("clang -ftime-trace Analysis")
    print(f"  Translation units analysed: {len(per_file)}")
    total_compile_ms = sum(s.total_ms for s in per_file.values())
    print(f"  Sum of compilation times:   {fmt_ms(total_compile_ms)}")
    print("  (Note: wall time < sum when parallel; sum shows where work goes)")

    # --- Slowest TUs ---
    print_section(f"Top {top_n} slowest translation units")
    print(f"  {'Total':>8}  {'Parse':>8}  {'Tmpl':>8}  {'Codegen':>8}  {'Opt':>8}  File")
    print(f"  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*36}")
    for src, stats in sorted(per_file.items(), key=lambda x: -x[1].total_ms)[:top_n]:
        if stats.total_ms < min_ms:
            continue
        p = fmt_ms(stats.by_category.get('parse', 0))
        t = fmt_ms(stats.by_category.get('instantiation', 0))
        c = fmt_ms(stats.by_category.get('codegen', 0))
        o = fmt_ms(stats.by_category.get('optimize', 0))
        name = Path(src).name
        print(f"  {fmt_ms(stats.total_ms):>8}  {p:>8}  {t:>8}  {c:>8}  {o:>8}  {name}")

    # --- Template instantiation hotspots ---
    print_section(f"Top {top_n} template instantiation hotspots (cumulative across all TUs)")
    print("  These are the single biggest lever for C++ compile time.")
    print()
    all_insts: dict[str, float] = collections.defaultdict(float)
    for stats in per_file.values():
        for tmpl, ms in stats.instantiations.items():
            all_insts[tmpl] += ms
    print(f"  {'Total':>8}  Template / Function")
    print(f"  {'-'*8}  {'-'*60}")
    for tmpl, ms in sorted(all_insts.items(), key=lambda x: -x[1])[:top_n]:
        if ms < min_ms:
            break
        # Truncate very long template names
        display = tmpl[:90] + '...' if len(tmpl) > 90 else tmpl
        print(f"  {fmt_ms(ms):>8}  {display}")

    # --- Header parse hotspots ---
    print_section(f"Top {top_n} headers by cumulative parse time")
    all_hdrs: dict[str, float] = collections.defaultdict(float)
    for stats in per_file.values():
        for hdr, ms in stats.header_parse.items():
            all_hdrs[hdr] += ms
    print(f"  {'Total':>8}  Header")
    print(f"  {'-'*8}  {'-'*60}")
    for hdr, ms in sorted(all_hdrs.items(), key=lambda x: -x[1])[:top_n]:
        if ms < min_ms:
            break
        display = hdr[-80:] if len(hdr) > 80 else hdr
        print(f"  {fmt_ms(ms):>8}  ...{display}" if len(hdr) > 80 else f"  {fmt_ms(ms):>8}  {display}")

    # --- Per-category breakdown across all TUs ---
    print_section("Time breakdown by compiler phase (all TUs combined)")
    grand: dict[str, float] = collections.defaultdict(float)
    for stats in per_file.values():
        for cat, ms in stats.by_category.items():
            grand[cat] += ms
    grand_total = sum(grand.values()) or 1
    for cat in ('parse', 'instantiation', 'codegen', 'optimize'):
        ms = grand.get(cat, 0)
        pct = 100 * ms / grand_total
        bar = '#' * int(pct / 2)
        print(f"  {cat:<16}  {fmt_ms(ms):>8}  {pct:5.1f}%  {bar}")

    # --- Per-module summary ---
    print_section("Per-module timing summary")
    by_mod: dict[str, list[float]] = collections.defaultdict(list)
    for src, stats in per_file.items():
        mod = module_of(src)
        by_mod[mod].append(stats.total_ms)
    print(f"  {'Module':<20}  {'Files':>5}  {'Total':>8}  {'Avg':>8}  {'Max':>8}")
    print(f"  {'-'*20}  {'-'*5}  {'-'*8}  {'-'*8}  {'-'*8}")
    for mod, times in sorted(by_mod.items(), key=lambda x: -sum(x[1])):
        print(f"  {mod:<20}  {len(times):>5}  {fmt_ms(sum(times)):>8}  "
              f"{fmt_ms(sum(times)/len(times)):>8}  {fmt_ms(max(times)):>8}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyse clang -ftime-trace JSON flamegraphs for GAMBIT.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--traces-dir', default=None)
    parser.add_argument('--build-dir', default=None)
    parser.add_argument('--top', type=int, default=30)
    parser.add_argument('--module', default=None)
    parser.add_argument('--min-ms', type=float, default=10.0)
    parser.add_argument('--output', default=None)
    parser.add_argument('--flamegraph', default=None)
    args = parser.parse_args()

    root = find_root()

    # Determine where to look for traces
    if args.traces_dir:
        search_path = Path(args.traces_dir)
    elif args.build_dir:
        search_path = Path(args.build_dir)
    else:
        # Default location from build_time_profile.sh
        search_path = root / 'build_profile' / 'profile_logs' / 'traces'

    if not search_path.exists():
        sys.exit(f"ERROR: Trace directory not found: {search_path}\n"
                 "Run build_time_profile.sh with clang++ first to generate traces.")

    print(f"Searching for clang trace files under {search_path} ...")
    traces = find_trace_files(search_path, args.module)
    if not traces:
        sys.exit(f"No clang trace JSON files found under {search_path}.\n"
                 "Make sure you built with: -DCMAKE_CXX_FLAGS=-ftime-trace")
    print(f"Found {len(traces)} trace files")

    t0 = time.time()
    per_file: dict[str, TraceStats] = {}
    all_events_for_flamegraph: list[dict] = []
    pid = 0
    for trace_path in traces:
        try:
            src, events = load_trace(trace_path)
            per_file[src] = analyse_trace(src, events)
            if args.flamegraph:
                for ev in events:
                    ev_copy = dict(ev)
                    ev_copy['pid'] = pid
                    all_events_for_flamegraph.append(ev_copy)
            pid += 1
        except Exception as e:
            print(f"  Warning: could not parse {trace_path}: {e}", file=sys.stderr)

    print(f"Parsed {len(per_file)} traces in {time.time()-t0:.1f}s")

    report(per_file, args.top, args.min_ms)

    if args.flamegraph:
        fg_path = Path(args.flamegraph)
        fg_path.write_text(json.dumps({'traceEvents': all_events_for_flamegraph}))
        print(f"\nCombined flamegraph written to {fg_path}")
        print("Open in chrome://tracing or https://ui.perfetto.dev")

    if args.output:
        summary = {
            'per_file': {
                src: {
                    'total_ms': stats.total_ms,
                    'by_category': dict(stats.by_category),
                    'top_instantiations': dict(
                        sorted(stats.instantiations.items(), key=lambda x: -x[1])[:20]
                    ),
                }
                for src, stats in per_file.items()
            }
        }
        Path(args.output).write_text(json.dumps(summary, indent=2))
        print(f"JSON summary written to {args.output}")


if __name__ == '__main__':
    main()
