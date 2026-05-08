#!/usr/bin/env bash
# build_time_profile.sh - Profile GAMBIT build times per translation unit.
#
# Instruments a fresh CMake build to record how long each source file takes
# to compile, then prints a ranked summary.  Supports two modes:
#
#   clang mode  (-ftime-trace)  Produces per-TU JSON flamegraphs showing
#               template instantiation, header parsing, and code-gen costs.
#               Requires clang++ >= 9.  Parse the traces with analyze_traces.py.
#
#   gcc mode    (wrapper)       Wraps each compiler invocation in /usr/bin/time
#               to record wall-clock time.  Works with any compiler.
#
# Usage:
#   bash scripts/build_profiling/build_time_profile.sh [OPTIONS]
#
# Options:
#   -b DIR      Build directory (default: build_profile/)
#   -j N        Parallel jobs (default: nproc)
#   -t TARGET   Make/ninja target (default: gambit)
#   -m MODULE   Only build one module, e.g. DarkBit (sets -Ditch= appropriately)
#   -c COMPILER Compiler: clang++ | g++ (default: auto-detect)
#   -O LEVEL    Optimisation level: 0 1 2 (default: 0 for speed of profiling)
#   -r          Re-use existing build dir (skip cmake configure step)
#   -n          Use ninja instead of make
#   -s          Summary only (skip building, just analyse existing logs)
#   -h          Show this help
#
# Examples:
#   # Profile a full build with clang (recommended):
#   bash scripts/build_profiling/build_time_profile.sh -c clang++ -j8
#
#   # Profile only DarkBit with g++, 4 jobs:
#   bash scripts/build_profiling/build_time_profile.sh -c g++ -m DarkBit -j4
#
#   # Re-analyse an existing profile build:
#   bash scripts/build_profiling/build_time_profile.sh -s -b build_profile/

set -euo pipefail

# ---- Defaults ---------------------------------------------------------------
BUILD_DIR="build_profile"
JOBS=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
TARGET="gambit"
MODULE=""
COMPILER=""
OPT_LEVEL="0"
REUSE=false
USE_NINJA=false
SUMMARY_ONLY=false

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${BUILD_DIR}/profile_logs"
TIME_LOG="${LOG_DIR}/compile_times.tsv"

# ---- Argument parsing -------------------------------------------------------
usage() { sed -n '3,50p' "$0" | sed 's/^# \?//'; exit 0; }

while getopts "b:j:t:m:c:O:rnsh" opt; do
  case $opt in
    b) BUILD_DIR="$OPTARG" ;;
    j) JOBS="$OPTARG" ;;
    t) TARGET="$OPTARG" ;;
    m) MODULE="$OPTARG" ;;
    c) COMPILER="$OPTARG" ;;
    O) OPT_LEVEL="$OPTARG" ;;
    r) REUSE=true ;;
    n) USE_NINJA=true ;;
    s) SUMMARY_ONLY=true ;;
    h) usage ;;
    *) usage ;;
  esac
done

# Auto-detect compiler
if [[ -z "$COMPILER" ]]; then
  if command -v clang++ &>/dev/null; then
    COMPILER="clang++"
  elif command -v g++ &>/dev/null; then
    COMPILER="g++"
  else
    echo "ERROR: No C++ compiler found. Pass -c clang++ or -c g++." >&2
    exit 1
  fi
fi

echo "============================================================"
echo "GAMBIT Build Time Profiler"
echo "  Root:        $ROOT_DIR"
echo "  Build dir:   $BUILD_DIR"
echo "  Compiler:    $COMPILER"
echo "  Target:      $TARGET"
echo "  Jobs:        $JOBS"
echo "  Opt level:   -O$OPT_LEVEL"
[[ -n "$MODULE" ]] && echo "  Module:      $MODULE"
echo "============================================================"

mkdir -p "$LOG_DIR"

# ---- Helper: detect clang ---------------------------------------------------
is_clang() {
  "$COMPILER" --version 2>&1 | grep -qi clang
}

# ---- Wrapper script for timing (gcc mode) -----------------------------------
WRAPPER="${LOG_DIR}/compiler_wrapper.sh"
cat > "$WRAPPER" <<'WRAPPER_EOF'
#!/usr/bin/env bash
# Thin wrapper: time the real compiler and append result to timing log.
REAL_COMPILER="$1"; shift
TIME_LOG="$1";      shift

start=$(date +%s%N)
"$REAL_COMPILER" "$@"
status=$?
end=$(date +%s%N)

elapsed_ms=$(( (end - start) / 1000000 ))

# Extract the source file from args (last .cpp/.cc/.cxx argument)
src_file=""
for arg in "$@"; do
  case "$arg" in *.cpp|*.cc|*.cxx|*.c) src_file="$arg" ;; esac
done

if [[ -n "$src_file" ]]; then
  echo -e "${elapsed_ms}\t${src_file}" >> "$TIME_LOG"
fi

exit $status
WRAPPER_EOF
chmod +x "$WRAPPER"

# ---- Configure step ---------------------------------------------------------
if [[ "$SUMMARY_ONLY" == false ]]; then
  if [[ "$REUSE" == false ]]; then
    echo ""
    echo "==> Configuring CMake ..."
    mkdir -p "$BUILD_DIR"

    CMAKE_ARGS=(
      -DCMAKE_BUILD_TYPE=None
      -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
    )

    if is_clang; then
      echo "    Using clang -ftime-trace for per-TU JSON flamegraphs"
      TRACE_FLAGS="-O${OPT_LEVEL} -ftime-trace"
      CMAKE_ARGS+=(
        -DCMAKE_CXX_COMPILER="$COMPILER"
        -DCMAKE_C_COMPILER="${COMPILER/++/}"
        "-DCMAKE_CXX_FLAGS=${TRACE_FLAGS}"
        "-DCMAKE_C_FLAGS=-O${OPT_LEVEL}"
      )
    else
      echo "    Using compiler wrapper + /usr/bin/time for per-TU timing"
      CMAKE_ARGS+=(
        -DCMAKE_CXX_COMPILER="$WRAPPER"
        "-DCMAKE_CXX_FLAGS=-O${OPT_LEVEL}"
      )
      # Store real compiler path so wrapper can find it
      echo "$COMPILER" > "${LOG_DIR}/real_compiler.txt"
      # Patch wrapper to embed real compiler
      sed -i "s|REAL_COMPILER=\"\$1\"; shift|REAL_COMPILER=\"${COMPILER}\"|" "$WRAPPER"
      sed -i "/REAL_COMPILER=\"\$1\"; shift/d" "$WRAPPER" 2>/dev/null || true
    fi

    if [[ -n "$MODULE" ]]; then
      # Build all modules EXCEPT the ones we don't want
      ALL_MODULES="Core Utils Elements Models Logs Printers ScannerBit \
        DarkBit ColliderBit NeutrinoBit DecayBit FlavBit SpecBit \
        PrecisionBit CosmoBit ObjectivesBit ExampleBit_A ExampleBit_B \
        Backends gum"
      DITCH_LIST=""
      for mod in $ALL_MODULES; do
        if [[ "$mod" != "$MODULE" && "$mod" != "Core" && "$mod" != "Utils" && \
              "$mod" != "Elements" && "$mod" != "Logs" ]]; then
          DITCH_LIST="${DITCH_LIST}${mod};"
        fi
      done
      CMAKE_ARGS+=("-Ditch=${DITCH_LIST}")
      echo "    Module filter: building $MODULE + core infrastructure"
    fi

    (cd "$BUILD_DIR" && cmake "${CMAKE_ARGS[@]}" "$ROOT_DIR")
  else
    echo "==> Re-using existing build directory (skipping configure)"
    # Clear old timing log so we get fresh data
    > "$TIME_LOG"
  fi

  # ---- Build step -----------------------------------------------------------
  echo ""
  echo "==> Building target: $TARGET (jobs: $JOBS) ..."
  BUILD_START=$(date +%s)

  if $USE_NINJA; then
    (cd "$BUILD_DIR" && ninja -j"$JOBS" "$TARGET" 2>&1 | tee "${LOG_DIR}/build.log")
  else
    (cd "$BUILD_DIR" && make -j"$JOBS" "$TARGET" 2>&1 | tee "${LOG_DIR}/build.log")
  fi

  BUILD_END=$(date +%s)
  TOTAL_SECS=$(( BUILD_END - BUILD_START ))
  echo "Total wall-clock build time: ${TOTAL_SECS}s ($(( TOTAL_SECS / 60 ))m $(( TOTAL_SECS % 60 ))s)"
  echo "$TOTAL_SECS" > "${LOG_DIR}/total_time.txt"
fi

# ---- Collect clang traces --------------------------------------------------
if is_clang 2>/dev/null && [[ "$SUMMARY_ONLY" == false || -d "$BUILD_DIR" ]]; then
  TRACE_COUNT=$(find "$BUILD_DIR" -name '*.json' -newer "${LOG_DIR}/build.log" 2>/dev/null | wc -l || echo 0)
  if (( TRACE_COUNT > 0 )); then
    TRACE_DEST="${LOG_DIR}/traces"
    mkdir -p "$TRACE_DEST"
    find "$BUILD_DIR" -name '*.json' -newer "${LOG_DIR}/build.log" \
      -exec cp {} "$TRACE_DEST/" \; 2>/dev/null || true
    TRACE_COUNT=$(ls "$TRACE_DEST/"*.json 2>/dev/null | wc -l || echo 0)
    echo "Collected ${TRACE_COUNT} clang trace files -> ${TRACE_DEST}/"
    echo ""
    echo "Tip: run analyze_traces.py to parse the flamegraph JSONs:"
    echo "  python3 scripts/build_profiling/analyze_traces.py --traces-dir ${TRACE_DEST}/"
  fi
fi

# ---- Summarise timing log (wrapper / make mode) ----------------------------
echo ""
echo "============================================================"
echo "BUILD TIME SUMMARY"
echo "============================================================"

if [[ -f "${LOG_DIR}/total_time.txt" ]]; then
  TOTAL=$(cat "${LOG_DIR}/total_time.txt")
  echo "Total wall-clock time: ${TOTAL}s"
fi

if [[ -f "$TIME_LOG" && -s "$TIME_LOG" ]]; then
  echo ""
  echo "Top 30 slowest translation units (ms):"
  echo ""
  printf "  %8s  %s\n" "ms" "File"
  printf "  %8s  %s\n" "--------" "--------------------------------------------"
  sort -rn "$TIME_LOG" | head -30 | while IFS=$'\t' read -r ms file; do
    rel="${file#${ROOT_DIR}/}"
    printf "  %8s  %s\n" "$ms" "$rel"
  done

  echo ""
  echo "Per-module timing summary:"
  echo ""
  printf "  %-20s  %8s  %6s  %10s  %10s\n" "Module" "Total(ms)" "Files" "Avg(ms)" "Max(ms)"
  printf "  %-20s  %8s  %6s  %10s  %10s\n" "--------------------" "--------" "------" "----------" "----------"

  declare -A mod_total mod_count mod_max
  while IFS=$'\t' read -r ms file; do
    rel="${file#${ROOT_DIR}/}"
    # Extract module name (first path component)
    mod=$(echo "$rel" | cut -d'/' -f1)
    mod_total[$mod]=$(( ${mod_total[$mod]:-0} + ms ))
    mod_count[$mod]=$(( ${mod_count[$mod]:-0} + 1 ))
    cur_max=${mod_max[$mod]:-0}
    (( ms > cur_max )) && mod_max[$mod]=$ms
  done < "$TIME_LOG"

  # Sort by total time descending
  for mod in "${!mod_total[@]}"; do
    echo "${mod_total[$mod]} $mod"
  done | sort -rn | while read -r total mod; do
    count=${mod_count[$mod]}
    avg=$(( total / count ))
    max=${mod_max[$mod]}
    printf "  %-20s  %8s  %6s  %10s  %10s\n" "$mod" "$total" "$count" "$avg" "$max"
  done
else
  echo ""
  echo "No per-file timing data found."
  if is_clang 2>/dev/null; then
    echo "(clang mode: see trace files in ${LOG_DIR}/traces/ and run analyze_traces.py)"
  else
    echo "Expected: ${TIME_LOG}"
  fi
fi

# ---- Object file sizes ------------------------------------------------------
echo ""
echo "============================================================"
echo "COMPILED ARTIFACT SIZES"
echo "============================================================"
echo ""

LIB_DIR="${BUILD_DIR}/lib"
if [[ -d "$LIB_DIR" ]]; then
  echo "Library sizes:"
  echo ""
  printf "  %10s  %s\n" "Size" "Library"
  printf "  %10s  %s\n" "----------" "------------------------------------------"
  find "$LIB_DIR" -name '*.a' -o -name '*.so' | sort | while read -r lib; do
    sz=$(du -sh "$lib" 2>/dev/null | cut -f1)
    printf "  %10s  %s\n" "$sz" "${lib#${BUILD_DIR}/}"
  done
else
  echo "(No lib/ directory found under $BUILD_DIR - build may not be complete)"
fi

echo ""
echo "============================================================"
echo "Next steps:"
echo "  1. Identify the slowest modules above"
echo "  2. Run:  python3 scripts/build_profiling/include_graph.py --module <NAME>"
echo "  3. Run:  python3 scripts/build_profiling/preprocess_size.py --build-dir $BUILD_DIR --module <NAME>"
if is_clang 2>/dev/null; then
  echo "  4. Run:  python3 scripts/build_profiling/analyze_traces.py --traces-dir ${LOG_DIR}/traces/"
fi
echo "  5. Run:  python3 scripts/build_profiling/binary_size.py --build-dir $BUILD_DIR"
echo "============================================================"
