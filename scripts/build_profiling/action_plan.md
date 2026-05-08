# GAMBIT Build Profiling — Prioritised Action Plan

Generated from static include-graph analysis and preprocessor expansion measurements
using the scripts in this directory.  All sizes are for clang++ 18, C++17, no
optimisation flags, using the default flags path (no compile\_commands.json).

---

## Summary of method

Four tools were run in sequence:

1. `include_graph.py` — static parse of all `#include` directives (no compilation).
   Produces in-degree counts, transitive include depths, and cross-module sharing.

2. `preprocess_size.py` — runs `clang++ -E` on each `.cpp` translation unit and
   measures how many bytes the compiler must parse.

3. `heavy_header_analysis.py` — runs `clang++ -E` on each *header* in isolation,
   then multiplies its standalone expansion size by its include-graph frequency to
   produce a **total compile cost** per header.  Also classifies headers as
   *trivial* (only `#undef`/`#include` wrapper content) or *structural*.

4. `analyze_traces.py` — parses clang `-ftime-trace` JSON flamegraphs to break
   compile time into parse / template-instantiation / codegen / optimisation phases
   (requires a full build; not yet run).

---

## False alarm: `backend_undefs.hpp` (320 inclusions)

**Status: no action required.**

The include graph flags this header as the single most-included file (320 direct
inclusions).  However `heavy_header_analysis.py` classifies it as *trivial*: it
contains 31 lines of `#undef` statements and resets exactly one `#define`.  Its
standalone preprocessed size is negligible.

The 320 inclusions are intentional and correct.  Every Backends frontend header and
every auto-generated BOSS wrapper class includes it as the last line to reset the
`BACKENDNAME`/`VERSION`/`BACKENDLANG` macros before the next backend is processed.
Removing or combining these includes would break the multi-backend macro isolation
that makes GAMBIT's ~80-backend architecture work.

---

## Root cause: the ~2 MB infrastructure floor

Almost every structural header in GAMBIT expands to ~2–2.5 MB when preprocessed
in isolation.  This manifests as:

- Core `.cpp` files: 2.4–3.1 MB each (162× average expansion for 17 files → 41 MB)
- DarkBit `.cpp` files: 4.3–9.3 MB each (332× average for 35 files → 159 MB)
- ColliderBit `.cpp` files: 2.6–3.9 MB each (367× average for 106 files → 296 MB)

The floor traces to a single chain:

```
util_types.hpp  (2,170 KB standalone, 69 direct inclusions)
├── variadic_functions.hpp  ← 1,610 KB — ENTIRELY standard library
│     <iostream>, <fstream>, <sstream>, <type_traits>, <cassert>
│     <map>, <unordered_map>, <set>, <unordered_set>
│     <vector>, <list>, <forward_list>, <deque>, <array>
├── standalone_error_handlers.hpp  (961 KB)
│     └── exceptions.hpp
│           └── util_macros.hpp  (675 KB — Boost.Preprocessor chains)
└── local_info.hpp  (652 KB)
```

`util_types.hpp` is itself a dependency of almost every GAMBIT header, so reducing
it propagates a saving to the entire codebase.

---

## Action A — Remove `variadic_functions.hpp` from `util_types.hpp`

**Estimated saving: ~1 MB × 69 direct inclusions = ~69 MB preprocessor work removed
from every build.  Many more TUs include `util_types.hpp` transitively, so the true
saving is larger.**

### Diagnosis

`util_types.hpp` includes `variadic_functions.hpp` unconditionally.
`variadic_functions.hpp` contains only standard-library includes — no GAMBIT
headers, no macros.  Its 1,610 KB expansion is entirely `<iostream>`, all the
associative and sequence containers, and `<type_traits>`.

`util_types.hpp` does *not* appear to use anything from `variadic_functions.hpp`
directly in its own declarations; the include is almost certainly a historical
convenience so that downstream code could rely on those containers being available
after including `util_types.hpp`.

### Proposed change

1. Remove `#include "gambit/Utils/variadic_functions.hpp"` from `util_types.hpp`.
2. Add targeted includes of only the STL headers actually used by `util_types.hpp`
   itself (likely `<map>`, `<string>`, `<complex>`, `<memory>`, and a few others
   already present as direct includes).
3. Find every file that relied on `variadic_functions.hpp` being pulled in
   transitively and add explicit includes where needed.  The compiler will report
   these immediately as missing-symbol errors.

### Risk

Medium.  Any file that relied on `variadic_functions.hpp` being available via
`util_types.hpp` will fail to compile until it adds its own include.  The fix for
each such file is mechanical (add one `#include`), but there may be many of them.
A targeted `grep` for usage of `std::unordered_map`, `std::list`, `std::deque`,
`std::array`, `std::forward_list` in files that do *not* include
`variadic_functions.hpp` directly will predict the breakage before any change is
made.

### Measurement baseline

```
util_types.hpp standalone:       2,170 KB
After removing variadic_functions: ~560 KB  (estimated: standalone_error_handlers
                                              + local_info + direct STL)
Saving per TU:                   ~1,610 KB
Total direct inclusions:              69
Conservative total saving:       ~108 MB preprocessor bytes
```

---

## Action B — Split `util_functions.hpp`

**Estimated saving (upper bound): ~2.2 MB × 96 inclusions = ~213 MB.**

### Diagnosis

`util_functions.hpp` is the single highest-cost header by total compile cost
(213 MB).  Its standalone expansion is 2.23 MB despite the file itself being only
~17 KB.  Its direct includes are:

```
util_functions.hpp (2,230 KB)
├── util_types.hpp      (2,170 KB — see Action A)
├── cmake_variables.hpp (small)
├── <boost/algorithm/string/split.hpp>
└── <boost/algorithm/string/classification.hpp>
```

The entire cost is from `util_types.hpp`.  After Action A is applied,
`util_functions.hpp` will shrink proportionally.

Additionally, most callers of `util_functions.hpp` only use a few of its ~30
utility functions.  A large fraction of those functions (`str_replace`,
`ensure_path_exists`, `merge_maps`, etc.) do not need the full Boost string
algorithm headers, which add ~50 KB on top of `util_types.hpp`.

### Proposed change

1. Create `util_functions_fwd.hpp` containing only forward declarations of the
   functions that callers use as opaque calls (e.g. `stringFMT`, `file_exists`,
   `ensure_path_exists`).  No Boost includes needed here.
2. Keep `util_functions.hpp` as the full definitions header for callers that need
   inline implementations or template functions.
3. Migrate the 96 callers to the forward-declaration header where possible.

### Risk

Low–medium.  Forward declarations of free functions are safe.  The risk is that
some callers use template functions from `util_functions.hpp` that cannot be
forward-declared; those must stay on the full header.

---

## Action C — Split `DarkBit_types.hpp` / isolate `daFunk.hpp`

**Estimated saving: ~2.4 MB × 23 inclusions of `DarkBit_utils.hpp` = ~55 MB.
Additional saving from the 34 inclusions of `DarkBit_rollcall.hpp` = ~100 MB.**

### Diagnosis

Every DarkBit `.cpp` file includes `DarkBit_rollcall.hpp`, which includes
`DarkBit_types.hpp`, which includes `daFunk.hpp` (1,755 lines of C++ template
code for the *daFunk* functional-programming library).

`daFunk::Funk` is used as a **value-type member** in `SimYieldTable`:

```cpp
// DarkBit_types.hpp line 156
daFunk::Funk dNdE;
daFunk::BoundFunk dNdE_bound;
```

Because `Funk` is a value member (not a pointer), the full definition of
`daFunk::Funk` is required wherever `SimYieldTable` is defined.  A forward
declaration of `daFunk::Funk` alone is not sufficient.

However, many DarkBit `.cpp` files do *not* construct or iterate over
`SimYieldTable` directly — they only call functions that *return* a `daFunk::Funk`.
For those callers, if `SimYieldTable` were moved to a separate header, they could
include a lightweight `DarkBit_types_fwd.hpp` instead.

### Proposed change

1. Create `DarkBit_types_fwd.hpp` containing forward declarations of all DarkBit
   types that do not have `daFunk` value members.
2. Move `SimYieldTable` (and anything else that stores `daFunk::Funk` by value)
   into `DarkBit_types_heavy.hpp` which includes the full `daFunk.hpp`.
3. Keep `DarkBit_types.hpp` as an umbrella that includes both, for backwards
   compatibility.
4. Audit which DarkBit `.cpp` files use `SimYieldTable` directly vs only use
   `daFunk::Funk` as a return type — those in the second group can switch to
   `DarkBit_types_fwd.hpp`.

### Risk

Medium–high.  `daFunk` types are pervasive in DarkBit.  Splitting the types header
requires auditing every DarkBit source file for direct use of `SimYieldTable`,
`SimYieldTable::addChannel`, etc.  A `grep -r "SimYieldTable"` across
`DarkBit/src/` will establish the scope before any change is made.

---

## Action D — Investigate `safety_bucket.hpp` → `functors.hpp` coupling

**Affects: every module `.cpp` file (DarkBit, ColliderBit, SpecBit, etc.).**

### Diagnosis

`safety_bucket.hpp` includes `functors.hpp` at line 28.  Together they form a
near-circular dependency (safety_bucket ← functors ← safety_bucket, broken only by
include guards).  Their standalone expansion sizes are almost identical:

```
safety_bucket.hpp  standalone: 2,540 KB
functors.hpp       standalone: 2,530 KB
```

Both are pulled into every module `.cpp` via:

```
gambit_module_headers.hpp
└── module_macros_inmodule.hpp
    └── module_macros_inmodule_defs.hpp
        └── safety_bucket.hpp
            └── functors.hpp  (2.53 MB)
```

`safety_bucket.hpp` needs `functors.hpp` because it defines `safe_ptr<functor>`
and `safe_ptr<module_functor<TYPE>>` template specialisations that reference the
functor base class.

### Proposed change

The cleanest fix is to split `functors.hpp` into:
- `functors_fwd.hpp` — forward declarations of `functor`, `module_functor<T>`,
  `primary_model_functor`, etc.
- `functors.hpp` — full definitions (keeps current content).

Then `safety_bucket.hpp` includes only `functors_fwd.hpp`.  Full `functors.hpp` is
included only where functor *objects* are constructed (i.e., the Core registration
machinery, not the module-side `.cpp` files).

### Risk

High.  `functors.hpp` is 1,134 lines of complex template code.  Forward-declaring
the functor hierarchy requires careful separation of the declaration and definition
layers.  This is the largest refactor in the list and should be attempted last,
after Actions A–C have been applied and measured.

### Baseline measurement

Every module `.cpp` file currently pays ~2.54 MB for `safety_bucket.hpp` as part
of the module-headers chain.  There are approximately 350 non-Backends module
`.cpp` files.  Reducing this to ~50 KB (forward declarations only) would save
roughly **875 MB** of preprocessor work across a full build — the single largest
potential saving in the codebase.

---

## Priority order and estimated total savings

| # | Action | Files affected | Estimated saving |
|---|--------|----------------|-----------------|
| A | Remove `variadic_functions.hpp` from `util_types.hpp` | ~69 direct + many transitive | **≥ 100 MB** |
| B | Split `util_functions.hpp` into fwd + definitions | 96 files | up to **213 MB** (partially realised after A) |
| C | Split `DarkBit_types.hpp` to isolate `daFunk.hpp` | ~57 DarkBit TUs | ~**55–100 MB** |
| D | Forward-declare functor hierarchy; decouple `safety_bucket.hpp` | ~350 module TUs | up to **875 MB** |

Actions A and B are the lowest risk and can be attempted in a single focused
session.  C requires a DarkBit-specific audit first.  D is a multi-session
refactor that should be validated with a full timed build before and after.

---

## How to re-run the analysis after each change

```bash
# Step 1: static analysis (no compilation needed, ~2 s)
python3 scripts/build_profiling/include_graph.py --output /tmp/include_graph.json

# Step 2: preprocessor cost per module (needs clang++, ~10–60 s per module)
python3 scripts/build_profiling/preprocess_size.py \
  --module Utils --compiler clang++ --jobs 8 --output /tmp/pp_utils.json

# Step 3: per-header total cost (needs clang++, ~5–10 min for full codebase)
python3 scripts/build_profiling/heavy_header_analysis.py \
  --jobs 8 --output /tmp/heavy_all.json

# Step 4: regenerate plots
python3 scripts/build_profiling/plot_build_profile.py
python3 scripts/build_profiling/plot_total_cost.py

# Step 5 (after a full build with clang -ftime-trace):
python3 scripts/build_profiling/analyze_traces.py \
  --traces-dir build_profile/profile_logs/traces/
```

Compare the `TotalCost` column in `heavy_header_analysis.py` output before and
after each change to measure progress without needing a full timed build.
