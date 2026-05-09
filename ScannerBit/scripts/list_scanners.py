#!/usr/bin/env python3
"""Print a status table of every known GAMBIT scanner plugin.

Combines three data sources:
  * the data file written by CMakeLists.txt at configure time (active external
    scanner make targets and per-Python-scanner status), passed in argv[1];
  * scratch/build_time/scanbit_excluded_libs.yaml (disabled native libs),
    produced by ScannerBit/CMakeLists.txt;
  * the scanner_plugin(name, version(...)) registrations under
    ScannerBit/src/scanners/, which are the canonical list of native plugins.

Prints one row per canonical plugin name. External plugins list their
versioned make targets; native-only plugins are tagged 'native'; Python
scanners are tagged 'python'.
"""
from __future__ import print_function

import io
import os
import re
import sys

import yaml


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, "..", ".."))


def parse_data_file(path):
    external_targets = []
    python_scanners = []
    with io.open(path, "r") as f:
        for line in f:
            if line.startswith("EXTERNAL_TARGETS="):
                external_targets = [s for s in line[len("EXTERNAL_TARGETS="):].rstrip("\n").split(";") if s]
            elif line.startswith("PYTHON_SCANNERS="):
                python_scanners = [s for s in line[len("PYTHON_SCANNERS="):].rstrip("\n").split(";") if s]
    return external_targets, python_scanners


def parse_excluded_yaml(path):
    """Return {libname: [reason, ...]} for every excluded library, where libname
    is the bare library identifier (e.g. "scanner_great", "scanner_python")."""
    excluded = {}
    if not os.path.exists(path):
        return excluded
    with io.open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    for libfile, info in data.items():
        # libfile looks like "libscanner_great.so" or "libobjective_python.so".
        name = libfile
        if name.startswith("lib"):
            name = name[3:]
        if name.endswith(".so"):
            name = name[:-3]
        raw_reasons = info.get("reason") or []
        if isinstance(raw_reasons, str):
            raw_reasons = [raw_reasons]
        # Each reason was emitted by ScannerBit/CMakeLists.txt as a literal
        # YAML sequence entry like '- file missing: "ROOT"', which the YAML
        # parser turns into a single-key mapping. Flatten back to "key: value".
        reasons = []
        for r in raw_reasons:
            if isinstance(r, dict):
                for k, v in r.items():
                    reasons.append("{}: {}".format(str(k).strip(), str(v).strip()))
            elif r is not None:
                s = str(r).strip()
                if s:
                    reasons.append(s)
        excluded[name] = reasons
    return excluded


_PLUGIN_RE = re.compile(
    r"scanner_plugin\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*version\s*\(\s*([^)]*)\)\s*\)"
)


def parse_native_plugins(scanners_dir):
    """Walk ScannerBit/src/scanners/<libdir>/*.cpp and collect every
    scanner_plugin(name, version(...)) registration. Returns a list of dicts:
    { 'libname': 'scanner_<libdir>', 'plugin': '<name>', 'version': '<v>' }.

    Skips the python/ directory; Python scanners come from a separate data
    source (cmake/python_scanners.cmake)."""
    rows = []
    if not os.path.isdir(scanners_dir):
        return rows
    for libdir in sorted(os.listdir(scanners_dir)):
        libpath = os.path.join(scanners_dir, libdir)
        if not os.path.isdir(libpath):
            continue
        if libdir == "python":
            continue
        libname = "scanner_" + libdir
        for root, _dirs, files in os.walk(libpath):
            for fname in files:
                if not fname.endswith((".cpp", ".cc", ".cxx", ".hpp", ".h")):
                    continue
                with io.open(os.path.join(root, fname), "r", errors="replace") as fh:
                    text = fh.read()
                for m in _PLUGIN_RE.finditer(text):
                    name = m.group(1)
                    parts = [p.strip() for p in m.group(2).split(",") if p.strip()]
                    ver = ".".join(parts)
                    rows.append({"libname": libname, "plugin": name, "version": ver})
    return rows


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: list_scanners.py <data_file>\n")
        sys.exit(2)

    external_targets, python_scanner_lines = parse_data_file(sys.argv[1])
    excluded = parse_excluded_yaml(
        os.path.join(_REPO, "scratch", "build_time", "scanbit_excluded_libs.yaml")
    )
    native = parse_native_plugins(os.path.join(_REPO, "ScannerBit", "src", "scanners"))

    # Map external make target to its companion plugin library, e.g.
    # "diver_1.3.0" -> "scanner_diver_1.3.0". Most ScannerBit/src/scanners/
    # subdirs include the version suffix, but a few (e.g. "great") do not, so
    # also register a versionless fallback mapping ("scanner_great").
    target_for_lib = {}
    for tgt in external_targets:
        target_for_lib.setdefault("scanner_" + tgt, tgt)
        if "_" in tgt:
            target_for_lib.setdefault("scanner_" + tgt.rsplit("_", 1)[0], tgt)

    # Group native+external plugins by canonical plugin name. Each entry is a
    # list of per-version dicts, sorted by version.
    grouped = {}
    for r in native:
        libname = r["libname"]
        target  = target_for_lib.get(libname, "")
        grouped.setdefault(r["plugin"], []).append({
            "version":  r["version"],
            "library":  libname,
            "target":   target,
            "disabled": libname in excluded,
            "reason":   "; ".join(excluded.get(libname, [])),
        })

    use_color = sys.stdout.isatty()
    YELLOW = "\033[33m" if use_color else ""
    DIM    = "\033[2m"  if use_color else ""
    RESET  = "\033[0m"  if use_color else ""

    def disable_tag(disabled):
        return (YELLOW + "[disabled]" + RESET) if disabled else " " * 10

    # Build (name, row-disabled, info-string, reason-string) tuples for the
    # grouped (native+external) section.
    grouped_rows = []
    for name in sorted(grouped, key=str.lower):
        versions = sorted(grouped[name], key=lambda v: v["version"])
        all_disabled = all(v["disabled"] for v in versions)
        any_disabled = any(v["disabled"] for v in versions)
        external_versions = [v for v in versions if v["target"]]
        native_versions   = [v for v in versions if not v["target"]]

        parts = []
        if external_versions:
            tgt_strs = []
            for v in external_versions:
                if v["disabled"] and not all_disabled:
                    tgt_strs.append("{} [disabled]".format(v["target"]))
                else:
                    tgt_strs.append(v["target"])
            parts.append("targets: " + ", ".join(tgt_strs))
        if native_versions and not external_versions:
            parts.append("native (no make targets)")
        info = "  ".join(parts)

        grouped_rows.append((name, all_disabled, any_disabled and not all_disabled, info))

    # Python rows: one per scanner. Status is libscanner_python lib status (if
    # excluded, all are disabled) overlaid with per-scanner Python module
    # availability.
    py_lib_disabled = "scanner_python" in excluded
    python_rows = []
    for line in python_scanner_lines:
        parts = line.split("|")
        if len(parts) < 2:
            continue
        pname = parts[0]
        pstatus = parts[1]
        disabled = py_lib_disabled or (pstatus != "enabled")
        python_rows.append((pname, disabled))

    # Compute column widths across both sections so they line up.
    all_names = [r[0] for r in grouped_rows] + [r[0] for r in python_rows]
    if not all_names:
        print("  (no scanner plugins found)")
        return
    name_w = max(len(n) for n in all_names)

    # Print grouped (native+external) rows.
    for name, all_disabled, partial, info in grouped_rows:
        if partial:
            tag = DIM + "[partial] " + RESET
        else:
            tag = disable_tag(all_disabled)
        print("  {n:<{nw}}  {tag}  {info}".format(
            n=name, nw=name_w, tag=tag, info=info))

    # Print Python rows (sorted alphabetically for parity with the grouped section).
    for name, disabled in sorted(python_rows, key=lambda r: r[0].lower()):
        print("  {n:<{nw}}  {tag}  python (no make targets)".format(
            n=name, nw=name_w, tag=disable_tag(disabled)))


if __name__ == "__main__":
    main()
