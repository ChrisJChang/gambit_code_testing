#!/usr/bin/env python3
"""
binary_size.py - Analyse compiled object and library sizes for GAMBIT.

After a successful CMake build this script walks the build tree, uses standard
binutils tools (nm, size, objdump) to report:

  - Per-module library sizes (text + data + bss sections)
  - Largest individual symbols (functions + global variables) across all objects
  - Symbol duplication: symbols appearing in multiple translation units with
    identical names but separate copies (indicates missing inline/template
    linkage savings or repeated non-inline definitions)
  - Biggest object files (individual .cpp.o files) within each module

This helps identify which modules contribute most to binary bloat and where
code-size reduction efforts will have the greatest impact.

Usage:
    python3 scripts/build_profiling/binary_size.py [OPTIONS]

Options:
    --build-dir DIR     CMake build directory (default: build_profile/)
    --root DIR          GAMBIT source root (auto-detected)
    --top N             Show top N entries (default: 40)
    --module MODULE     Restrict to one module
    --min-kb N          Minimum kilobytes to report a symbol (default: 4)
    --output FILE       Write JSON summary to FILE
    --nm-tool CMD       nm binary to use (default: nm, falls back to llvm-nm)

Examples:
    python3 scripts/build_profiling/binary_size.py --build-dir build/
    python3 scripts/build_profiling/binary_size.py --build-dir build/ --module DarkBit --top 20
    python3 scripts/build_profiling/binary_size.py --build-dir build/ --output sizes.json
"""

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


GAMBIT_MODULES = [
    'Core', 'Utils', 'Elements', 'Models', 'Logs', 'Printers', 'ScannerBit',
    'DarkBit', 'ColliderBit', 'NeutrinoBit', 'DecayBit', 'FlavBit',
    'SpecBit', 'PrecisionBit', 'CosmoBit', 'ObjectivesBit',
    'ExampleBit_A', 'ExampleBit_B', 'Backends', 'gum',
]


def find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / 'CMakeLists.txt').exists() and (parent / 'Core').exists():
            return parent
    return Path('.').resolve()


def find_nm() -> str:
    for cmd in ('nm', 'llvm-nm', 'llvm-nm-14', 'llvm-nm-15', 'llvm-nm-16',
                'llvm-nm-17', 'llvm-nm-18'):
        if shutil.which(cmd):
            return cmd
    return 'nm'


def find_size_tool() -> str:
    for cmd in ('size', 'llvm-size', 'llvm-size-14'):
        if shutil.which(cmd):
            return cmd
    return 'size'


def collect_objects(build_dir: Path, module: str | None) -> list[Path]:
    objects = []
    for dirpath, _, filenames in os.walk(build_dir):
        dp = Path(dirpath)
        # Skip external/contrib build artifacts
        rel = dp.relative_to(build_dir)
        parts = rel.parts
        if parts and parts[0] in ('_deps', 'contrib'):
            continue
        for fn in filenames:
            p = dp / fn
            if fn.endswith('.o') or fn.endswith('.a') or fn.endswith('.so'):
                if module and module.lower() not in str(dp).lower():
                    continue
                objects.append(p)
    return objects


def run_nm(nm_tool: str, path: Path) -> list[tuple[int, str, str]]:
    """Run nm and return list of (size_bytes, type, name)."""
    results = []
    try:
        out = subprocess.run(
            [nm_tool, '--print-size', '--size-sort', '--radix=d', str(path)],
            capture_output=True, text=True, timeout=60,
        )
        for line in out.stdout.splitlines():
            parts = line.split(maxsplit=3)
            if len(parts) >= 4:
                try:
                    size = int(parts[1])
                    sym_type = parts[2]
                    name = parts[3]
                    results.append((size, sym_type, name))
                except ValueError:
                    pass
            elif len(parts) == 3:
                try:
                    size = int(parts[0])
                    sym_type = parts[1]
                    name = parts[2]
                    results.append((size, sym_type, name))
                except ValueError:
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return results


def run_size(size_tool: str, path: Path) -> dict:
    """Run 'size' and return {'text': N, 'data': N, 'bss': N} in bytes."""
    try:
        out = subprocess.run(
            [size_tool, str(path)],
            capture_output=True, text=True, timeout=30,
        )
        lines = out.stdout.strip().splitlines()
        if len(lines) >= 2:
            # BSD format: text data bss dec hex filename
            # System V format may differ
            parts = lines[-1].split()
            if len(parts) >= 3:
                try:
                    return {'text': int(parts[0]), 'data': int(parts[1]), 'bss': int(parts[2])}
                except ValueError:
                    pass
    except Exception:
        pass
    return {'text': 0, 'data': 0, 'bss': 0}


def module_of_path(path: Path, build_dir: Path) -> str:
    rel = str(path.relative_to(build_dir) if path.is_relative_to(build_dir) else path)
    for mod in GAMBIT_MODULES:
        if mod in rel:
            return mod
    return 'other'


def demangle(name: str) -> str:
    """Attempt to demangle a C++ symbol name."""
    try:
        result = subprocess.run(
            ['c++filt', name], capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() or name
    except Exception:
        return name


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyse compiled binary sizes for GAMBIT.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--build-dir', default='build_profile')
    parser.add_argument('--root', default=None)
    parser.add_argument('--top', type=int, default=40)
    parser.add_argument('--module', default=None)
    parser.add_argument('--min-kb', type=float, default=4.0)
    parser.add_argument('--output', default=None)
    parser.add_argument('--nm-tool', default=None)
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else find_root()
    build_dir = Path(args.build_dir).resolve()
    nm_tool = args.nm_tool or find_nm()
    size_tool = find_size_tool()
    min_bytes = int(args.min_kb * 1024)
    top_n = args.top

    if not build_dir.exists():
        sys.exit(f"ERROR: Build directory not found: {build_dir}")

    print(f"Build directory: {build_dir}")
    print(f"nm tool:         {nm_tool}")
    print(f"size tool:       {size_tool}")

    # ---- Collect all object/library files -----------------------------------
    all_objects = collect_objects(build_dir, args.module)
    obj_files = [f for f in all_objects if f.suffix == '.o']
    lib_files = [f for f in all_objects if f.suffix in ('.a', '.so')]
    print(f"Found {len(obj_files)} object files, {len(lib_files)} libraries")

    # ---- Section sizes per library ------------------------------------------
    print_section("Library section sizes")
    lib_sizes = []
    for lib in sorted(lib_files):
        secs = run_size(size_tool, lib)
        disk = lib.stat().st_size
        lib_sizes.append({'path': str(lib), 'disk': disk, **secs})

    lib_sizes.sort(key=lambda x: -(x['text'] + x['data']))
    print(f"  {'Disk':>9}  {'Text':>9}  {'Data':>9}  {'BSS':>9}  Library")
    print(f"  {'-'*9}  {'-'*9}  {'-'*9}  {'-'*9}  {'-'*36}")
    for ls in lib_sizes[:top_n]:
        name = Path(ls['path']).name
        print(f"  {fmt_bytes(ls['disk']):>9}  {fmt_bytes(ls['text']):>9}  "
              f"{fmt_bytes(ls['data']):>9}  {fmt_bytes(ls['bss']):>9}  {name}")

    # ---- Object file sizes by module ----------------------------------------
    print_section("Per-module object file size summary")
    by_mod: dict[str, list[tuple[int, Path]]] = collections.defaultdict(list)
    for obj in obj_files:
        try:
            sz = obj.stat().st_size
            mod = module_of_path(obj, build_dir)
            by_mod[mod].append((sz, obj))
        except OSError:
            pass

    print(f"  {'Module':<20}  {'Files':>5}  {'Total':>10}  {'Avg':>9}  {'Max':>9}")
    print(f"  {'-'*20}  {'-'*5}  {'-'*10}  {'-'*9}  {'-'*9}")
    for mod, items in sorted(by_mod.items(), key=lambda x: -sum(s for s, _ in x[1])):
        total = sum(s for s, _ in items)
        avg = total // len(items)
        mx = max(s for s, _ in items)
        print(f"  {mod:<20}  {len(items):>5}  {fmt_bytes(total):>10}  "
              f"{fmt_bytes(avg):>9}  {fmt_bytes(mx):>9}")

    # ---- Largest individual object files ------------------------------------
    print_section(f"Top {top_n} largest object files")
    all_obj_sizes = [(obj.stat().st_size, obj) for obj in obj_files if obj.exists()]
    all_obj_sizes.sort(key=lambda x: -x[0])
    print(f"  {'Size':>9}  {'Module':<16}  File")
    print(f"  {'-'*9}  {'-'*16}  {'-'*48}")
    for sz, obj in all_obj_sizes[:top_n]:
        mod = module_of_path(obj, build_dir)
        rel = obj.relative_to(build_dir) if obj.is_relative_to(build_dir) else obj
        print(f"  {fmt_bytes(sz):>9}  {mod:<16}  {rel}")

    # ---- Symbol analysis via nm ---------------------------------------------
    print_section(f"Top {top_n} largest symbols across all object files")
    print("  (Collecting symbols via nm — this may take a minute ...)")

    all_syms: list[tuple[int, str, str, str]] = []  # (size, type, name, obj)
    sym_occurrences: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)  # name -> [(size, obj)]

    for obj in obj_files:
        mod = module_of_path(obj, build_dir)
        syms = run_nm(nm_tool, obj)
        for size, sym_type, name in syms:
            if size >= min_bytes:
                all_syms.append((size, sym_type, name, mod))
            sym_occurrences[name].append((size, mod))

    all_syms.sort(key=lambda x: -x[0])

    print(f"\n  {'Size':>9}  {'Type':>4}  {'Module':<16}  Symbol")
    print(f"  {'-'*9}  {'-'*4}  {'-'*16}  {'-'*44}")
    shown = 0
    for size, sym_type, name, mod in all_syms:
        if shown >= top_n:
            break
        # Skip weak/undefined symbols, focus on defined code/data
        if sym_type.lower() in ('u', 'w', 'v'):
            continue
        display = demangle(name)
        if len(display) > 80:
            display = display[:77] + '...'
        print(f"  {fmt_bytes(size):>9}  {sym_type:>4}  {mod:<16}  {display}")
        shown += 1

    # ---- Duplicated symbols (same name in multiple objects) -----------------
    print_section(f"Top {top_n} duplicated symbols (same name in multiple TUs)")
    print("  Multiple copies of the same symbol wastes binary space and suggests")
    print("  non-inline function definitions in headers or missed link-time dedup.")
    print()
    duplicates = [(name, occs) for name, occs in sym_occurrences.items()
                  if len(occs) > 1 and sum(s for s, _ in occs) >= min_bytes]
    duplicates.sort(key=lambda x: -(len(x[1]) * (sum(s for s, _ in x[1]) // len(x[1]))))

    print(f"  {'Copies':>6}  {'TotalWaste':>10}  {'PerCopy':>9}  Symbol")
    print(f"  {'-'*6}  {'-'*10}  {'-'*9}  {'-'*44}")
    for name, occs in duplicates[:top_n]:
        n = len(occs)
        total = sum(s for s, _ in occs)
        per = total // n if n else 0
        if per < min_bytes:
            continue
        display = demangle(name)
        if len(display) > 70:
            display = display[:67] + '...'
        print(f"  {n:>6}  {fmt_bytes(total):>10}  {fmt_bytes(per):>9}  {display}")

    # ---- JSON output --------------------------------------------------------
    if args.output:
        results = {
            'libraries': lib_sizes,
            'per_module': {
                mod: {
                    'files': len(items),
                    'total_bytes': sum(s for s, _ in items),
                    'avg_bytes': sum(s for s, _ in items) // len(items),
                }
                for mod, items in by_mod.items()
            },
            'top_symbols': [
                {'size': s, 'type': t, 'module': m, 'name': demangle(n)}
                for s, t, n, m in all_syms[:200]
            ],
            'top_duplicates': [
                {
                    'name': demangle(name),
                    'copies': len(occs),
                    'total_bytes': sum(s for s, _ in occs),
                }
                for name, occs in duplicates[:100]
            ],
        }
        Path(args.output).write_text(json.dumps(results, indent=2))
        print(f"\nJSON results written to {args.output}")

    print()
    print("=" * 72)
    print("Next steps:")
    print("  1. Large modules → investigate with include_graph.py and preprocess_size.py")
    print("  2. Many duplicated symbols → consider moving definitions to .cpp files")
    print("  3. Large template symbols → consider explicit instantiation or splitting templates")
    print("=" * 72)


if __name__ == '__main__':
    main()
