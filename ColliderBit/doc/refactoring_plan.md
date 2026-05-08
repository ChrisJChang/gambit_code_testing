# ColliderBit Refactoring Plan

## Background and Motivation

ColliderBit has grown organically over many years, which has produced some architectural patterns that make new additions harder than they should be. The clearest recent example is the addition of initial cross-sections (`InitialTotalCrossSection`), which required:

- Inserting a new special iteration phase (`XSEC_CALCULATION = -4`) into the ordered enum of loop phases
- Threading a new GAMBIT dependency (`Dep::InitialTotalCrossSection`) directly into the body of `operateLHCLoop`
- Coordinating changes across `ColliderBit_eventloop.cpp`, `ColliderBit_eventloop_utils.hpp`, `MCLoopInfo.hpp`, `getxsec.cpp`, and multiple rollcall headers

The analyses framework is already well-modularised (each analysis is a self-contained class). The problem is everything else — in particular the event loop and the cross-section machinery — which mixes concerns in a way that makes it difficult to understand and extend individual pieces.

This document describes a set of refactoring proposals ordered from highest to lowest priority. They are designed to be undertaken independently; none requires the others as a prerequisite.

---

## Proposal 1: Introduce a `ColliderPipeline` abstraction to decompose `operateLHCLoop`

### Problem

`operateLHCLoop` (`ColliderBit_eventloop.cpp:97`) is a 400-line monolithic function that is simultaneously responsible for:

- Parsing and validating all YAML run options for every collider
- Computing the desired event count (`desired_nEvents`) for each collider, including the dependency on `InitialTotalCrossSection`
- Managing the OpenMP-parallel inner event loop with thread-safe counters
- Driving convergence checking
- Sequencing the 10 special iteration phases (BASE_INIT through BASE_FINALIZE)
- Silencing/restoring stdout

Adding any new phase (as happened with `XSEC_CALCULATION`) means modifying this function directly, understanding all of its local state, and finding the right insertion point in the middle of its nested loops and conditionals.

The special iterations are named integer constants defined in `ColliderBit_eventloop_utils.hpp:50`:

```cpp
enum specialIterations { BASE_INIT = -1, COLLIDER_INIT = -2, COLLIDER_INIT_OMP = -3,
                         XSEC_CALCULATION = -4, START_SUBPROCESS = -5,
                         COLLECT_CONVERGENCE_DATA = -6, CHECK_CONVERGENCE = -7,
                         END_SUBPROCESS = -8, COLLIDER_FINALIZE = -9, BASE_FINALIZE = -10 };
```

These raw integers make it impossible to reason about phase ordering or insert new phases without renumbering existing ones.

### Proposed Solution

Extract a `ColliderRunPhase` pipeline class that owns the sequencing logic, and shrink `operateLHCLoop` to a coordinator that calls into it.

**Step 1 — Replace the raw enum with a strongly-typed phase sequence.**

Replace the integer enum with a `std::vector<ColliderPhase>` that describes the ordered phases and their parallelism mode:

```cpp
struct ColliderPhase {
    std::string name;
    int iteration_id;       // passed to Loop::executeIteration
    bool omp_parallel;      // wrap in #pragma omp parallel?
    bool single_per_collider; // reset between colliders?
};
```

A factory function `default_collider_phases()` returns the canonical sequence. New phases can be inserted by modifying only this function.

**Step 2 — Extract a `runColliderPhases` free function.**

Move the per-collider phase dispatch loop out of `operateLHCLoop` into its own translation unit (`ColliderBit_phases.cpp`). Its signature:

```cpp
void runColliderPhases(const std::vector<ColliderPhase>& phases,
                       const std::string& collider,
                       MCLoopInfo& info);
```

This function knows about `piped_errors`/`piped_warnings` checks and OMP parallelism, but nothing about YAML options or event counts.

**Step 3 — Extract a `ColliderRunConfig` builder.**

Move the first-time YAML-parsing block (lines 114–211) into a dedicated `buildColliderRunConfig(Options&, MCLoopInfo&)` function. This makes the config-parsing logic testable in isolation and removes the `static bool first` pattern.

**Step 4 — Extract the event count calculation.**

The block at lines 168–186 that reads `InitialTotalCrossSection` and calls `calc_N_MC` is the piece most likely to change when new cross-section modes are added. Move it into a free function:

```cpp
int computeDesiredEventCount(const std::string& collider,
                             const ColliderRunConfig& config,
                             const xsec_map_t& xsec_map);
```

This removes the direct `Dep::InitialTotalCrossSection` access from the main event loop body, replacing it with a passed-in value.

**Result:** `operateLHCLoop` becomes a ~60-line coordinator:
1. Call `buildColliderRunConfig` (once)
2. Call `Loop::executeIteration(BASE_INIT)`
3. For each collider: call `computeDesiredEventCount`, then `runColliderPhases` (pre-event phases), then the inner event loop, then `runColliderPhases` (post-event phases)
4. Call `Loop::executeIteration(BASE_FINALIZE)`

**Expected effort:** ~1 week. Purely mechanical reorganisation; behaviour must be bit-for-bit identical.

**Risk:** Medium. The GAMBIT loop/pipe machinery makes this slightly non-trivial; care required with the `static` variables that hold run-options state.

---

## Proposal 2: Split `getxsec.cpp` by backend

### Problem

`getxsec.cpp` is 1,916 lines and contains cross-section retrieval functions for at least five distinct backends:

- `simplexs` (Python, `#ifdef HAVE_PYBIND11`)
- `prospino` (Fortran backend)
- NLLFast (interpolation tables)
- YAML-specified values (direct user input)
- SLHA-file-based values
- A "testing" stub with hardcoded numbers

Each backend has its own YAML option parsing, unit conversion, and error handling, all sharing the same file. When a new backend is added, the developer must read the entire file to understand the existing patterns and avoid name collisions.

The helper `convert_xsecs_to_fb` (lines 35–72) is duplicated conceptually with logic in `xsec.cpp`.

### Proposed Solution

Split into one file per backend:

```
src/
  xsec/
    xsec_utils.cpp           # convert_xsecs_to_fb and other shared helpers
    getxsec_simplexs.cpp      # simplexs backend
    getxsec_prospino.cpp      # prospino backend
    getxsec_nllfast.cpp       # NLLFast backend
    getxsec_yaml.cpp          # YAML-specified values
    getxsec_testing.cpp       # testing stub
```

Each file includes only its backend's headers and declares only its own module functions. A shared header `include/.../xsec_utils.hpp` exposes `convert_xsecs_to_fb` and the `PID_pair` helper types.

This makes it straightforward to add a new backend: create one new `.cpp` file and one new capability declaration in the rollcall header, without touching any existing code.

**Expected effort:** 2–3 days. Mechanical split; no logic changes.

**Risk:** Low. File-level reorganisation with no behaviour change.

---

## Proposal 3: Break up `ColliderBit_LEP.cpp` by physics topic

### Problem

`ColliderBit_LEP.cpp` is 2,766 lines covering:

- Chargino/neutralino pair production likelihoods
- Slepton pair production likelihoods  
- Higgs searches at LEP
- Oblique corrections / electroweak precision observables
- LEP cross-section computations delegating to `lep_mssm_xsecs.cpp`

A developer working on, say, the slepton limits must search through 2,700 lines to find the relevant code, navigating past unrelated Higgs and EWK material.

### Proposed Solution

Split by physics topic:

```
src/
  ColliderBit_LEP_charginos.cpp
  ColliderBit_LEP_sleptons.cpp
  ColliderBit_LEP_Higgs.cpp
  ColliderBit_LEP_EWK.cpp
  ColliderBit_LEP_xsecs.cpp      # absorbs lep_mssm_xsecs.cpp
```

The corresponding rollcall entries (currently mixed in one large block in `ColliderBit_rollcall.hpp`) should be split into per-topic rollcall fragments and `#include`d from the main rollcall.

**Expected effort:** 3–4 days.

**Risk:** Low–Medium. The split is mostly mechanical but must be verified against the rollcall's `NEEDS_CLASSES_DECLARED` and `ALLOW_MODELS` annotations, which impose ordering constraints.

---

## Proposal 4: Split `ColliderBit_InterpolatedYields.cpp`

### Problem

`ColliderBit_InterpolatedYields.cpp` is 2,491 lines. It mixes:

- The interpolation engine itself (grid lookup, bilinear interpolation)
- Model-specific yield tables for multiple BSM models (DMEFT, SubGeVDM, etc.)
- Likelihood calculation for each model
- Result caching and scaling logic

Each BSM model that uses interpolated yields adds hundreds of lines to the same file.

### Proposed Solution

Separate the generic machinery from model-specific content:

```
src/
  interpolated_yields/
    InterpolatedYields_engine.cpp   # grid lookup, bilinear interp, caching
    InterpolatedYields_DMEFT.cpp
    InterpolatedYields_SubGeVDM.cpp
    InterpolatedYields_ExternalModel.cpp
```

The engine exposes a clean interface (a class or a set of free functions taking a grid path and a parameter point) that each model file calls. Adding a new model then requires only a new ~200-line file.

**Expected effort:** 3–5 days (some logic disentanglement needed).

**Risk:** Medium. The caching and scaling logic is currently tightly interleaved with the model-specific code; extracting a clean boundary requires care.

---

## Proposal 5: Formalise the cross-section pipeline with a `XsecProvider` interface

### Problem

Cross-section access is currently done through an ad-hoc combination of:

- `Dep::InitialTotalCrossSection` — a GAMBIT dependency on a `map<string, xsec_container>`
- `Dep::PIDPairCrossSectionsMap` — per-process cross-sections
- Direct access to `Dep::SLHA1Spectrum` inside `getxsec.cpp` to read masses
- The `complete_process_PID_pair_multimaps` utility to map Pythia process codes to PID pairs

This is the architecture that made the `XSEC_CALCULATION` phase addition difficult: there was no single abstraction representing "the cross-section information available before the event loop starts", so it had to be wired in directly as a new loop phase.

### Proposed Solution

Define a `XsecProvider` concept (as either an abstract base class or a concept-constrained template) that standardises how cross-section sources expose themselves:

```cpp
struct XsecProvider {
    // Called once before the event loop, with the current model point.
    // Returns false if the point should be vetoed (e.g. zero total cross-section).
    virtual bool initialise(const ModelParameters&) = 0;

    // Total cross-section (fb) for a given collider.
    virtual double totalXsec(const std::string& collider) const = 0;

    // Per-PID-pair cross-sections (fb), if available.
    virtual map_PID_pair_PID_pair_xsec perProcessXsecs() const = 0;
};
```

Each backend in `getxsec.cpp` (Proposal 2) would implement this interface. `operateLHCLoop` would hold a `XsecProvider*` rather than a direct `Dep::` access; the GAMBIT dependency graph would inject the correct provider via the existing capability mechanism.

This decouples the event loop from the specific cross-section source in use, and makes it trivial to add a new source (implement the interface, register the capability) without touching `operateLHCLoop`.

**Expected effort:** 1–2 weeks (requires Proposals 1 and 2 as prerequisites for a clean implementation, though it can be done independently).

**Risk:** Medium–High. Introduces a new abstraction layer that must integrate with the GAMBIT dependency resolution system.

---

## Proposal 6: Performance improvements

These are lower-certainty opportunities identified during the structural analysis. Each needs profiling to confirm the payoff before implementation.

### 6a: Avoid re-constructing `AnalysisContainer` in `GetMaxLumi`

`GetMaxLumi` (called once per collider in `operateLHCLoop`) constructs and then immediately discards an `AnalysisContainer` just to read luminosities. If the container is already constructed elsewhere for the same analysis list (which it is, at `COLLIDER_INIT`), the luminosities could be cached or passed in directly. For scan points with many colliders, this saves O(N_analyses) allocations per point.

### 6b: Thread-local analysis containers

The `AnalysisContainer` is currently shared across OMP threads with lock-protected access during event dispatch (`runAnalyses.cpp`). Making each OMP thread own its own `AnalysisContainer` (initialised at `COLLIDER_INIT_OMP`, merged at `COLLIDER_FINALIZE`) would eliminate the lock on the hot path. This mirrors how Pythia instances are already handled (one per thread). The merge at finalisation is a simple per-signal-region addition.

This is likely the highest-impact performance change available without algorithmic improvements, since analysis dispatch is in the innermost loop.

### 6c: Avoid redundant PID-pair map lookups in `getxsec.cpp`

The `complete_process_PID_pair_multimaps` functions are called on every iteration in which `getxsec` functions run. The maps are deterministic given the collider settings and do not depend on the model point; they should be computed once at `COLLIDER_INIT` and cached.

### 6d: Early cross-section veto before `COLLIDER_INIT_OMP`

If `InitialTotalCrossSection` is near-zero for a given collider, the entire event loop for that collider can be skipped before any OMP threads are spawned. Currently a debug message exists for this case (line 179 of `ColliderBit_eventloop.cpp`) but no actual skip. A configurable threshold veto here would avoid spawning threads and initialising Pythia for parameter-space regions where the signal is negligible.

---

## Summary and Recommended Order

| # | Proposal | Effort | Risk | Primary Benefit |
|---|----------|--------|------|-----------------|
| 1 | Decompose `operateLHCLoop` | 1 week | Medium | Future loop phases easy to add |
| 2 | Split `getxsec.cpp` | 2–3 days | Low | Future xsec backends easy to add |
| 3 | Split `ColliderBit_LEP.cpp` | 3–4 days | Low–Med | Navigability of LEP physics |
| 4 | Split `ColliderBit_InterpolatedYields.cpp` | 3–5 days | Medium | Future BSM models easy to add |
| 5 | `XsecProvider` interface | 1–2 weeks | Med–High | Decouples xsec from event loop |
| 6 | Performance improvements | 1–3 days each | Low | Runtime speedup |

The most impactful pair for day-to-day development is **Proposals 1 + 2**: they directly address the pain point experienced during the initial cross-section addition, and both have low risk of introducing bugs since they are pure reorganisations with no logic changes.

Proposals 3 and 4 improve navigability but do not change the architecture; they are good candidates for a separate sprint.

Proposal 5 is the most architecturally ambitious and should only be started after 1 and 2 are merged and stable, since it depends on the cleaner structure they create.

The performance proposals (6) are independent and can be tackled opportunistically, but should be profiled first on a representative scan to confirm they are worth the effort.
