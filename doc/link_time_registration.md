# Link-time (self-registering) module registration — prototype

CMake option: `-DLINK_TIME_REGISTRATION=On` (default `Off`). Migrated so far:
**ExampleBit_A** only. Everything else uses the legacy compile-time path, and the
two mechanisms coexist so migration can proceed Bit by Bit.

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
-DCMAKE_BUILD_TYPE=Release`, GCC 13.3, 4 cores. Experiment:
`touch ExampleBit_A/include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp && time make gambit`.

| | legacy (`OFF`) | link-time (`ON`) |
|---|---|---|
| objects recompiled | (see build logs) | (see build logs) |
| wall time | (see build logs) | (see build logs) |

(Filled in from the captured logs in the final commit; see
`doc/link_time_registration_logs/`.)

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
  containers keyed/sorted downstream), but log lines such as the functor list
  ordering may differ cosmetically between configurations.
- **Standalones**: unchanged by construction (verified by building
  `ExampleBit_A_standalone` in both configurations).
- **`QUICK_FUNCTION`-style ad-hoc declarations in the Core** would be a blocker if
  any Core source declared extra functions for a migrated Bit at compile time;
  none do for ExampleBit_A (or any other Bit; the pattern only appears in
  standalone mains, which keep their own expansion).
