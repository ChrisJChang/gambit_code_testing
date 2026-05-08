# ColliderBit Refactoring Plan

## Background and Motivation

The central difficulty for new contributors to ColliderBit is understanding how events flow from the generator through to analyses. The data flow is encoded implicitly in the GAMBIT capability/type resolution system, spread across rollcall declarations in at least four header files (`ColliderBit_MC_rollcall.hpp`, `models/SUSY.hpp`, `models/SUSY_extras.hpp`, `ColliderBit_measurements_rollcall.hpp`). There is no single place where a developer can read the pipeline and understand what calls what.

The specific symptom is the capabilities `HardScatteringSim` and `HardScatteringEvent`. Both have multiple functions registered under them that return different C++ types. In GAMBIT, a downstream `DEPENDENCY` on the same capability with a different type is resolved to a different function — so the type annotation is the only thing that distinguishes intermediate pipeline steps from final products. This is not obvious to someone who doesn't already know the pattern.

---

## The Current Pipeline (reconstructed)

Understanding what currently exists is the starting point for any refactoring.

### `HardScatteringSim`

Three functions are registered under this one capability:

| Function | Return type | Defined in | Purpose |
|---|---|---|---|
| `getPythia` | `Py8Collider_defaultversion` | `models/SUSY.hpp` | Construct and own the Pythia8 instance (MSSM models) |
| `getPythia_SLHA` | `Py8Collider_defaultversion` | `models/SUSY_extras.hpp` | Same, but for SLHA file/scan models |
| `getPythiaAsBase` | `const BaseCollider*` | `models/SUSY.hpp` | Return a pointer-to-base wrapping whichever `Py8Collider_defaultversion` was chosen |

Downstream consumers request either `Py8Collider_defaultversion` (when they need Pythia-specific methods, e.g., extracting process codes or cross-sections) or `const BaseCollider*` (when they only need the generic interface). The GAMBIT dependency resolver selects the right function based on the type in the `DEPENDENCY` declaration.

The coupling between `getPythia`/`getPythia_SLHA` and `getPythiaAsBase` is hidden: `getPythiaAsBase` depends on `HardScatteringSim` (as `Py8Collider_defaultversion`) but is itself also registered under `HardScatteringSim`. This chain is invisible unless you read all three files together.

### `HardScatteringEvent`

Seven functions are registered under this one capability, producing three different types:

**Pythia path:**

| Function | Return type | Depends on | Purpose |
|---|---|---|---|
| `generateEventPythia` | `Pythia_default::Pythia8::Event` | `HardScatteringSim` (as `Py8Collider_defaultversion`) | Run Pythia, return raw generator event |
| `generateEventPythia_HEPUtils` | `HEPUtils::Event` | `HardScatteringEvent` (as `Pythia8::Event`) | Convert raw Pythia event to analysis format |
| `generateEventPythia_HepMC` | `HepMC3::GenEvent` | `HardScatteringEvent` (as `Pythia8::Event`) | Convert raw Pythia event to HepMC format |

**File-reading paths (no generator):**

| Function | Return type | Purpose |
|---|---|---|
| `getLHEvent_HEPUtils` | `HEPUtils::Event` | Read LHE file, convert to analysis format |
| `getHepMCEvent` | `HepMC3::GenEvent` | Read HepMC file |
| `getHepMCEvent_HEPUtils` | `HEPUtils::Event` | Read HepMC file, convert to analysis format |
| `convertHepMCEvent_HEPUtils` | `HEPUtils::Event` | Depends on `HardScatteringEvent` (as `HepMC3::GenEvent`) to convert |

**Downstream consumers and which type they request:**

- `smearEventATLAS`, `smearEventCMS`, `copyEvent` → `HardScatteringEvent` as `HEPUtils::Event`
- Rivet measurements → `HardScatteringEvent` as `HepMC3::GenEvent`
- `generateEventPythia_HEPUtils`, `generateEventPythia_HepMC` → `HardScatteringEvent` as `Pythia8::Event`

The result is that `HardScatteringEvent` is simultaneously:
1. A raw generator output (`Pythia8::Event`)
2. An intermediate HepMC representation (`HepMC3::GenEvent`)
3. The final analysis-ready event (`HEPUtils::Event`)

And some functions within the capability depend on other functions within the same capability, which cannot be seen without reading all the rollcall headers simultaneously.

---

## Proposal: Rename capabilities to reflect their role in the pipeline

The core fix is to give each distinct stage in the event pipeline its own capability name. The GAMBIT type resolution mechanism still works exactly as before; we are only changing names so the dependency graph becomes readable.

### Revised capability names

**Instead of `HardScatteringSim` (two different things):**

- `HardScatteringSim` — keep this name, but restrict it to the concrete Pythia type (`Py8Collider_defaultversion`). This is the capability that owns the generator instance.
- `HardScatteringSimBase` — new name for the `const BaseCollider*` view of the same simulator. Any consumer that only needs the generic interface (process codes, xsec queries) uses this.

**Instead of `HardScatteringEvent` (three different things):**

- `GeneratorRawEvent` — the backend-native event object before any conversion. Currently `Pythia_default::Pythia8::Event` for the Pythia path. A future generator backend would register its own type here.
- `HardScatteringEvent` — keep this name, but restrict it to `HEPUtils::Event` only. This is the format analyses consume; it is the one true "hard scattering event" from ColliderBit's perspective.
- `HardScatteringHepMCEvent` — the `HepMC3::GenEvent` format needed by Rivet measurements. This is a parallel branch from `GeneratorRawEvent`, not a step toward `HardScatteringEvent`.

### What changes in each rollcall file

**`models/SUSY.hpp`:**
- `getPythia` and `getPythia_SLHA` stay under `HardScatteringSim` (returning `Py8Collider_defaultversion`) — no change.
- `getPythiaAsBase` moves to `HardScatteringSimBase` (returning `const BaseCollider*`).
- `generateEventPythia` moves from `HardScatteringEvent` to `GeneratorRawEvent`.
- `generateEventPythia_HEPUtils` stays under `HardScatteringEvent`; its `DEPENDENCY` changes from `HardScatteringEvent, Pythia8::Event` to `GeneratorRawEvent, Pythia8::Event`.
- `generateEventPythia_HepMC` moves to `HardScatteringHepMCEvent`; its `DEPENDENCY` changes similarly.

**`ColliderBit_MC_rollcall.hpp`:**
- All `DEPENDENCY(HardScatteringSim, const BaseCollider*)` change to `DEPENDENCY(HardScatteringSimBase, const BaseCollider*)`.
- `smearEventATLAS/CMS/copyEvent` keep `DEPENDENCY(HardScatteringEvent, HEPUtils::Event)` — no change.
- `getHepMCEvent` moves to `HardScatteringHepMCEvent`.
- `getLHEvent_HEPUtils`, `getHepMCEvent_HEPUtils` stay under `HardScatteringEvent`.
- `convertHepMCEvent_HEPUtils` changes its dependency from `HardScatteringEvent, HepMC3::GenEvent` to `HardScatteringHepMCEvent, HepMC3::GenEvent`.

**`ColliderBit_measurements_rollcall.hpp`:**
- `DEPENDENCY(HardScatteringEvent, HepMC3::GenEvent)` changes to `DEPENDENCY(HardScatteringHepMCEvent, HepMC3::GenEvent)`.

**`generateEventPy8Collider.hpp`:**
- The macro definitions that reference `Dep::HardScatteringEvent` for `Pythia8::Event` change to `Dep::GeneratorRawEvent`.

### What the pipeline looks like after the rename

```
HardScatteringSim (Py8Collider_defaultversion)
  └─ HardScatteringSimBase (const BaseCollider*)   [used by xsec queries]

GeneratorRawEvent (Pythia8::Event)
  ├─ HardScatteringEvent (HEPUtils::Event)         [used by all analyses]
  └─ HardScatteringHepMCEvent (HepMC3::GenEvent)   [used by Rivet measurements]

(file-reading paths produce HardScatteringEvent or HardScatteringHepMCEvent directly,
 bypassing GeneratorRawEvent entirely — which is now explicit)
```

A developer adding a new generator backend can now see exactly which capabilities they need to fill: provide `HardScatteringSim` with their concrete type, provide `GeneratorRawEvent` with their raw event type, and provide a converter to `HardScatteringEvent`. The `HardScatteringHepMCEvent` path is optional and only needed for Rivet.

### Expected effort and risk

- **Effort:** 2–3 days. Purely a renaming exercise across ~6 files; no logic changes.
- **Risk:** Low. GAMBIT's capability resolution is purely name+type based, so as long as all declarations and dependencies are updated consistently, behaviour is unchanged. The main risk is missing an occurrence; a grep for the old names after the change will catch any stragglers.
- **Testing:** A full test run with an MSSM scan and an SLHA-file scan (to exercise both `getPythia` and `getPythia_SLHA` paths) and a Rivet measurement run (to exercise the `HardScatteringHepMCEvent` path) should suffice.

---

## Secondary proposal: Consolidate rollcall declarations for the event pipeline

Even after the rename, the declarations for the event pipeline are spread across four header files with no obvious reason for the split other than historical growth:

- `ColliderBit_MC_rollcall.hpp` — generic/infrastructure functions
- `models/SUSY.hpp` — MSSM-specific generator and event functions  
- `models/SUSY_extras.hpp` — SLHA-file/scan-model generator function
- `ColliderBit_measurements_rollcall.hpp` — Rivet path

A developer adding a new generator backend must discover all four files to understand the full picture, and must decide which file their new declarations belong in.

A cleaner organisation would be a single header dedicated to the event pipeline:

```
include/gambit/ColliderBit/ColliderBit_eventpipeline_rollcall.hpp
```

containing all declarations for `HardScatteringSim`, `HardScatteringSimBase`, `GeneratorRawEvent`, `HardScatteringEvent`, and `HardScatteringHepMCEvent` — with model restrictions (`ALLOW_MODELS`) kept exactly as they are. The four existing files would `#include` this header (or it would be included by the top-level rollcall).

This is a lower-priority change since it does not affect runtime behaviour and involves more file restructuring, but it makes the "where do I put my new generator?" question have a clear answer.

**Effort:** 1 day (after the renaming proposal is done). **Risk:** Very low.
