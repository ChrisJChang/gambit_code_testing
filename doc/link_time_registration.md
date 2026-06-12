# Link-time (self-registering) module registration — prototype

CMake option: `-DLINK_TIME_REGISTRATION=On` (default `Off`). Migrated:
**all Bits** (ColliderBit, CosmoBit, DarkBit, DecayBit, ExampleBit_A,
ExampleBit_B, FlavBit, NeutrinoBit, ObjectivesBit, PrecisionBit, SpecBit) and
the **Backends** (all frontend headers).  With the option ON,
`module_rollcall.hpp` contains no module rollcall headers at all and
`gambit.hpp` no longer includes `backend_rollcall.hpp`; `gambit.cpp` expands
only the model rollcall.  Only the **Models** remain on the legacy
compile-time path; the two mechanisms coexist (the option defaults to OFF, and
partially-migrated configurations work, as the incremental history of this
branch demonstrates).

## The problem

Every Bit's rollcall header is `#include`d into the Core by the generated
`Core/include/gambit/Core/module_rollcall.hpp`, whose only consumer is
`Core/src/gambit.cpp` (via `gambit.hpp`). The rollcall macros expand there in the
"in-core" context (`Elements/include/gambit/Elements/module_macros_incore_defs.hpp`),
producing every module functor *definition* plus its registration calls — all in one
enormous translation unit. Consequently, editing any Bit's rollcall header recompiles
`gambit.cpp` (the largest TU in the Core) and relinks everything.

## What the in-core macros actually do

For a single module function (worked example: `ExampleBit_A::nevents_pred`,
capability `nevents`, type `double`, one `DEPENDENCY(xsection, double)`), the in-core
expansion performs:

`START_MODULE` (once per module), in `namespace Gambit::ExampleBit_A`:

- Defines `ExampleBit_A_error()` / `ExampleBit_A_warning()` accessors
  (function-local statics) and namespace-scope references that force their creation.
- `register_module_with_log("ExampleBit_A")` — adds a log tag via the
  `Logging::tag2str()` / `Logging::components()` function-local-static registries.
- `register_module("ExampleBit_A", <REFERENCE>)` → `Core().registerModule(...)`
  (module name + citation key list, used by diagnostics and the dependency resolver).
- A `Utils::python_interpreter_guard` global (keeps pybind11 alive through static init).
- Generic (fallback) `resolve_dependency` / `resolve_backendreq` /
  `rt_register_*` function templates, later specialised per dependency/requirement.

`START_CAPABILITY` / `DECLARE_FUNCTION`:

- Declares tag structs `Gambit::Tags::nevents`, `Gambit::Tags::nevents_pred`
  (incomplete types used only as template arguments, TU-local).
- Prototypes `void nevents_pred(double&)` (defined in the module's own sources).
- Defines the functor global `Functown::nevents_pred` of type
  `module_functor<double>` (or `model_functor` for `ModelParameters`); its
  constructor takes `Models::ModelDB()` (the claw singleton) by reference.
- Defines the `Pipes::nevents_pred` globals: the `Param` safe-parameter map,
  `ModelInUse` function pointer, `runOptions`, `Downstream::dependees`/`subcaps`
  safe pointers, and (for loop managers) the `Loop` pipes.
- `register_function(...)` — connects those pipes to the functor's internals.
- `register_module_functor_core(...)` → `Core().registerModuleFunctor(...)`.

`DEPENDENCY` / `NEEDS_MANAGER` / `ALLOW_MODEL(S)` / `BACKEND_REQ` / etc.:

- Define a `dep_bucket<TYPE>` / `BE*_bucket` safety bucket in `Pipes::<fn>::Dep`
  (or `::BEreq`), an explicit specialisation of `resolve_dependency`
  / `resolve_backendreq` that downcasts the resolving functor and initialises the
  bucket, and a `register_*` call that stores capability/type strings and the
  resolver function pointer in the functor object. `NEEDS_MANAGER` additionally
  calls `register_management_req(...)` → `Core().registerNestedModuleFunctor(...)`.

### The key observation

Every one of these side effects is either (a) a definition local to the expanding
TU, or (b) a call on a *function-local-static* singleton (`Core()`,
`Models::ModelDB()`, `Backends::backendInfo()`, the logging registries) made by a
namespace-scope `const int ... = register_*(...)` initialiser. In other words,
**GAMBIT's in-core macros are already a self-registration system, safe against the
static-initialisation-order fiasco**. The Core does not consume any compile-time
knowledge from the rollcall headers other than these expansions; `gambit.cpp`,
the dependency resolver, the likelihood container and the diagnostics all operate
purely on the runtime registries. There is no need for a new registry or registrar
class: the entire fix is to *relocate the expansion into a TU owned by the module*.

## What the prototype does

With `-DLINK_TIME_REGISTRATION=On`:

1. **Harvester** (`module_harvester.py -r ExampleBit_A`, driven from the top-level
   `CMakeLists.txt` via `MODULE_HARVESTER_EXTRA_ARGS`): ExampleBit_A is harvested
   exactly as before — its functor types still enter `module_functor_types.hpp`
   (so the central explicit template instantiations in `Core/src/functors.cpp`
   still cover it), its types header still enters `module_types_rollcall.hpp`,
   it still appears in `config/gambit_bits.yaml` and the standalone type pickles —
   but its rollcall header is **omitted from the include list** in
   `module_rollcall.hpp`. The Core no longer compiles anything from ExampleBit_A.

2. **Registration TU** (`ExampleBit_A/registration/ExampleBit_A_registration.cpp`):
   guarded by `#ifdef LINK_TIME_REGISTRATION`, it does precisely what
   `module_rollcall.hpp` used to do for this Bit:

   ```cpp
   #include "gambit/Elements/module_macros_incore.hpp"
   #include "gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp"
   ```

   `cmake/executables.cmake` compiles this file **into the `gambit` executable
   only** (one entry per migrated Bit in `LINK_TIME_REGISTRATION_BITS`). It must
   not join the Bit's OBJECT library, because standalone executables
   (`make ExampleBit_A_standalone`) link those same objects together with their
   own in-core expansion compiled from the standalone main via
   `standalone_module.hpp` (with `STANDALONE` defined) — adding the registration
   TU there would produce duplicate definitions of every `Functown::` functor.
   Because the object file is passed directly to the linker (no archive), no
   dead-stripping or hidden-visibility issue arises; registration runs pre-main,
   single-threaded, as before.

3. **Determinism fix** (independent benefit, also applied to the legacy path):
   the generated headers (`module_types_rollcall.hpp`, `module_functor_types.hpp`,
   `backend_functor_types.hpp`, standalone functor lists) were emitted in Python
   set iteration order, which changes from run to run, and `module_rollcall.hpp`
   was rewritten unconditionally on every harvest. Both meant that *any* harvester
   re-run dirtied headers included by every TU in the tree, masking incremental
   builds. All generated lists are now sorted and `module_rollcall.hpp` is only
   rewritten when its content changes.

### Rebuild scope after the change

Touching `ExampleBit_A/include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp` now
recompiles:

- the module harvester re-run (output unchanged → no generated headers dirtied),
- `ExampleBit_A`'s own objects that include the rollcall header
  (`src/ExampleBit_A.cpp` in the in-module context),
- the registration TU,
- one link of `gambit`.

On the legacy path the same touch additionally recompiles `Core/src/gambit.cpp`
(the in-core expansion of *all* rollcall headers). See "Measurements" below.

## Measurements

Build configuration: `-DBits="ExampleBit_A;ExampleBit_B" -DWITH_MPI=Off
-DCMAKE_BUILD_TYPE=Release`, GCC 13.3, 4 cores. Experiment (after a full build
and a no-op `make gambit` showing 0 recompilations):
`touch ExampleBit_A/include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp && time make gambit`.

| | legacy (`OFF`) | link-time (`ON`) |
|---|---|---|
| objects recompiled | `ExampleBit_A.cpp.o`, **`Core/src/gambit.cpp.o`**, link | `ExampleBit_A.cpp.o`, `ExampleBit_A_registration.cpp.o`, link |
| wall time | 1m50.4s | 0m23.6s |

Raw logs: `doc/link_time_registration_logs/`. The Core's largest TU no longer
rebuilds; the gap grows with the number/size of Bits in the build (this
configuration contains only the two small ExampleBits — in a full build,
`gambit.cpp` expands every Bit's rollcall header).

With ColliderBit also in the build (`-DBits="ColliderBit;ExampleBit_A;ExampleBit_B"
-DWITH_HEPMC=ON -DWITH_YODA=OFF`, same machine), repeating the experiments:

| touch | legacy (`OFF`) | link-time (`ON`) |
|---|---|---|
| `ColliderBit_rollcall.hpp` | 23 ColliderBit TUs + **`gambit.cpp`** + link, 9m22s | 23 ColliderBit TUs + `ColliderBit_registration.cpp` + link, 7m04s |
| `ExampleBit_A_rollcall.hpp` | `ExampleBit_A.cpp` + **`gambit.cpp`** + link, 4m57s | `ExampleBit_A.cpp` + `ExampleBit_A_registration.cpp` + link, 0m31s |

Two observations. First, the cross-Bit isolation is the headline: once a big Bit
is in the build, the legacy path makes *every* Bit's rollcall edit pay the
full `gambit.cpp` recompile (ExampleBit_A: 4m57s → 31s, ~10x). Second, for the
big Bit itself most of the remaining cost is its own 23 source files, which
include the rollcall header and rebuild on either path — reducing that is a
module-internal layout question (e.g. splitting rollcall includes), orthogonal
to Core coupling.

With the backends also migrated, touching one frontend header
(`Backends/include/gambit/Backends/frontends/LibFirst_1_0.hpp`):

| | legacy (`OFF`) | link-time (`ON`) |
|---|---|---|
| objects recompiled | **`gambit.cpp`** + link | `Backends_registration.cpp` + link |
| wall time | 4m32s | 0m55s |

(The frontend's own `.cpp`, when enabled in the configuration, rebuilds on
either path.)

With **all Bits** in the build (no `-DBits` restriction, `-DBUILD_FS_MODELS=None`,
`-DWITH_HEPMC=ON -DWITH_YODA=OFF`, same machine; 1654 module functors and 1610
backend functors registered):

| touch | legacy (`OFF`) | link-time (`ON`) |
|---|---|---|
| `DarkBit_rollcall.hpp` | 30 DarkBit TUs + **`gambit.cpp`** + link, 33m12s | 30 DarkBit TUs + `DarkBit_registration.cpp` + link, 9m47s |
| `ExampleBit_A_rollcall.hpp` | `ExampleBit_A.cpp` + **`gambit.cpp`** + link, (see logs) | `ExampleBit_A.cpp` + `ExampleBit_A_registration.cpp` + link, 0m49s |

In the full configuration the `gambit.cpp` recompile alone costs roughly
twenty-five minutes on this machine, and the legacy path pays it for *every*
rollcall edit in *any* Bit.

Runtime equivalence (same configuration, `spartan.yaml` with the built-in
`random` scanner standing in for the external `diver`): both configurations
register exactly 240 module functors and 84 backend functors, the logged
masterGraph functor table (origin, function, capability, type, status, #deps,
#backend-reqs) is byte-identical, and the dependency-resolution log content
(candidate vertices, applied rules, evaluation order) is identical after
stripping timestamps. Remaining log differences are unseeded scanner
randomness, per-point runtime estimates, and printer-ID assignment order
(registry iteration order shifts because ExampleBit_A now registers from its
own TU — cosmetic; see Caveats). `make ExampleBit_A_standalone` builds and
runs successfully in both configurations.

## ColliderBit migration (second Bit, first non-trivial one)

ColliderBit was migrated as the stress test: its rollcall is a tree of five
sub-rollcall headers, two of which are *generated* at build time by
`collider_harvester.py` (`ColliderBit_models_rollcall.hpp`,
`Py8Collider_typedefs.hpp`); it is dense with conditional-compilation guards
(`HAVE_PYBIND11`, `EXCLUDE_HEPMC`, `EXCLUDE_YODA`); it uses BOSSed Pythia types
in backend requirements, loop-managed event-loop functors, model groups, and
`NEEDS_CLASSES_FROM`. Findings:

- **One real hidden coupling found and fixed**: the in-core expansions of
  `NEEDS_CLASSES_FROM` (→ `set_classload_requirements`) and
  `ACTIVATE_BACKEND_REQ_FOR_MODELS` (→ `set_backend_rule_for_model`) call
  functions declared in `Backends/ini_functions.hpp`, which the in-core macro
  header never included. The legacy path only compiles because `gambit.hpp`
  happens to include `backend_rollcall.hpp` *before* `module_rollcall.hpp`.
  `module_macros_incore_defs.hpp` now includes the declarations it uses, making
  the in-core context self-contained. No other order-dependent declaration was
  hit by the full ColliderBit rollcall tree.
- **Config-guard consistency is automatic**: `HAVE_PYBIND11`, `EXCLUDE_HEPMC`
  and `EXCLUDE_YODA` all come from the generated `cmake_variables.hpp`, so the
  registration TU, the module objects and the (legacy) Core expansion always
  agree on which rollcall sections exist.
- **Generated sub-headers need no special handling**: the registration TU is a
  source of the `gambit` target, which depends on the ColliderBit object
  library, which depends on `collider_harvest` — the same transitive ordering
  that protects `module_harvest` today.
- The migration itself was exactly the advertised recipe: one two-include
  registration TU plus one entry in `LINK_TIME_REGISTRATION_BITS`.

### Validation environment caveat

The validation build used `-DWITH_YODA=OFF` (a new, explicit opt-out added in
this branch — the YODA tarball host is unreachable from the build sandbox;
HepMC3 3.2.5 was supplied as the authentic md5-verified tarball). YODA-guarded
measurement functions are therefore compiled out *identically in both
configurations*, so the legacy-vs-link-time comparison is unaffected, but the
`EXCLUDE_YODA=0` sections of the measurements rollcall have not been exercised
under link-time registration. They use the same macros as the rest of the tree
(no new macro kinds), so no new failure mode is expected. CBS
(`ColliderBit Solo`) does not build in this YODA-less configuration in *either*
mode — its main source unconditionally references the Rivet/Contur/nulike
frontends, which the configuration excludes — verified to fail identically
(same first error in `solo.cpp`) with the option OFF and ON, i.e. a property
of the configuration, not of link-time registration. CBS links the ColliderBit
object library plus its own in-core expansion from `standalone_module.hpp`,
neither of which this change touches.

Runtime equivalence with ColliderBit migrated: both configurations register
exactly 463 module and 135 backend functors; the masterGraph functor table
(464 rows, 214 of them ColliderBit) is byte-identical; the dependency
resolution log differs only in timestamps, printer-ID assignment order and
unseeded scanner output, as before.

## Backends migration

The backends were migrated as a third step. They do not fit the per-Bit CMake
pattern, so the wiring differs:

- `backend_rollcall.hpp` (the list of all frontend headers) is generated by the
  *backend* harvester and `#include`d directly by `gambit.hpp`. No harvester
  change is involved: when `LINK_TIME_REGISTRATION` is ON, `gambit.hpp` simply
  skips the include via the global compile definition, and a single
  registration TU (`Backends/registration/Backends_registration.cpp`, again
  linked only into the `gambit` executable) expands it instead. `gambit.cpp`
  itself has no compile-time dependency on any backend declaration.
- Granularity is the whole Backends directory: the frontend list is dynamic
  (harvested, with config-dependent exclusions), so per-frontend TUs would
  need code generation. Editing one frontend header therefore recompiles the
  one registration TU (which includes *all* frontend headers) plus the
  frontend's own source file — still a fraction of a `gambit.cpp` compile.
- `backend_macros.hpp` already includes `functor_definitions.hpp`, so the
  registration TU instantiates the functor templates it needs locally.

### The static-initialisation-order bug this exposed (and its fix)

This migration hit the predicted cross-TU initialisation-order hazard for
real: the in-core expansion of `NEEDS_CLASSES_FROM(Pythia, default)` (in
ColliderBit's registration TU) calls `set_classload_requirements`, which
translated version strings via `backendInfo().version_from_safe_version()` —
maps that are only populated once the Pythia frontend's `LOAD_LIBRARY`
registration has run. In the legacy single-TU world the order was guaranteed
by `gambit.hpp`'s include order (backends before modules); with separate
registration TUs the order is link-order, and the binary aborted pre-main
("The backend "Pythia" is not known to GAMBIT").

Following the prototype design rule (record passively, defer real work),
`set_classload_requirements` now applies the requirement immediately when the
backend's version information is already available, and otherwise queues it;
`backend_info::link_versions` retries the queue every time any backend
registers a version. Registration is thereby order-independent *by
construction* — no reliance on link order. A requirement that is still
unfulfilled after static initialisation (i.e. the backend never registered at
all — a configuration that previously *terminated pre-main* in the legacy
path) is now reported as a proper error by
`check_deferred_classload_requirements()`, called from
`gambit_core::accountForMissingClasses()`. Standalone executables still
register backends before modules within their single TU, so they take the
immediate path and behave exactly as before.

This was the only order-sensitive registration step found: all other
module-side registrations store strings/function pointers in the functor
itself, and all backend-side registrations only touch `backendInfo()`/`Core()`
singletons.

## What remains to migrate a real Bit

Per Bit, the migration recipe is mechanical:

1. Create `<Bit>/registration/<Bit>_registration.cpp` (two includes, as above).
2. Add the Bit to `LINK_TIME_REGISTRATION_BITS` in the top-level `CMakeLists.txt`.

Things that stay central (deliberately, for now):

- **Explicit functor template instantiations**: `module_functor<T>` member
  definitions live in `functor_definitions.hpp` and are instantiated centrally in
  `Core/src/functors.cpp` from the harvested `module_functor_types.hpp`. A migrated
  Bit introducing a *new* return type still dirties that one list (one Core TU
  recompiles — much smaller than `gambit.cpp`). A follow-up could instead include
  `functor_definitions.hpp` in each registration TU and harvest a reduced central
  list, making type additions module-local too.
- **Models**: `model_rollcall.hpp` is still compiled into the Core. Model-module
  functors (primary model parameter functors) use additional registration calls
  (`register_model_functor_core`, claw bookkeeping) but follow the same
  self-registering pattern, so the same relocation should work for
  `Models/models/*.hpp` if wanted; it is out of scope of this prototype.
- **Backends**: `backend_rollcall.hpp` likewise still compiles into the Core.
  Backend functors are registered through the same kind of static-init calls
  (`register_backend_functor` → `Core().registerBackendFunctor`), so the pattern
  extends, but the backend macro machinery (BOSS, classloading) was not audited.
- **Harvesters/GUM/printers**: unaffected. The `-r` option changes only the
  include list of `module_rollcall.hpp`; all other harvester outputs are
  byte-identical, and the printer harvester does not read rollcall headers.

### Caveats / behavioural differences found

- **Registration order across TUs**: within one TU, registration order follows the
  rollcall header top-to-bottom, as before. *Across* modules the order is now
  unspecified (link order in practice) instead of `module_rollcall.hpp` include
  order. Nothing in the Core depends on registration order (registries are
  containers keyed/sorted downstream), but iteration order over
  `Core().getModuleFunctors()` shifts: observed as different (but internally
  consistent) printer-ID assignments in the logs. Scan output labels and values
  are unaffected.
- **One-definition headers**: `Utils/static_members.hpp` *defines* static data
  members and is pulled in by the in-core macro header, so a registration TU
  would duplicate them against the main TU. It now honours
  `GAMBIT_NO_STATIC_MEMBER_DEFINITIONS`, which registration TUs define. Any
  future header that defines objects from the in-core context would need the
  same treatment (this was the only one in the current tree).
- **Standalones**: unchanged by construction (verified by building
  `ExampleBit_A_standalone` in both configurations).
- **`QUICK_FUNCTION`-style ad-hoc declarations in the Core** would be a blocker if
  any Core source declared extra functions for a migrated Bit at compile time;
  none do for ExampleBit_A (or any other Bit; the pattern only appears in
  standalone mains, which keep their own expansion).
