# Touch-test evidence logs

Experiment, run in both configurations after a successful full build and a no-op
`make gambit` (0 recompilations):

    touch ExampleBit_A/include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp
    time make gambit

Configuration: `-DBits="ExampleBit_A;ExampleBit_B" -DWITH_MPI=Off
-DCMAKE_BUILD_TYPE=Release`, GCC 13.3.0, 4 cores, cmake 3.28 (Makefiles).

| configuration | objects recompiled | wall time |
|---|---|---|
| `LINK_TIME_REGISTRATION=Off` (`touch_test_legacy.log`) | `ExampleBit_A/src/ExampleBit_A.cpp.o`, `Core/src/gambit.cpp.o`, link | 1m50.4s |
| `LINK_TIME_REGISTRATION=On` (`touch_test_ltr.log`)  | `ExampleBit_A/src/ExampleBit_A.cpp.o`, `ExampleBit_A/registration/ExampleBit_A_registration.cpp.o`, link | 0m23.6s |

In the legacy configuration the Core's largest translation unit
(`Core/src/gambit.cpp`, which #includes every Bit's rollcall header via the
generated `module_rollcall.hpp`) rebuilds on every rollcall edit.  With
link-time registration it does not; only the Bit's own objects rebuild, and
the difference grows with the number and size of Bits in the build (this
measurement used the two small ExampleBits only).

Both configurations were measured with the harvested-header determinism fix
in place (sorted generation + write-only-if-changed for module_rollcall.hpp).
Without that fix, *both* configurations intermittently rebuild near-everything
after any harvester re-run, because the generated type-header include order
was randomised by Python set iteration.

## ColliderBit round

Configuration: `-DBits="ColliderBit;ExampleBit_A;ExampleBit_B" -DWITH_HEPMC=ON
-DWITH_YODA=OFF -DWITH_MPI=Off -DCMAKE_BUILD_TYPE=Release`, same machine.
Same protocol (full build, no-op `make gambit` showing 0 recompiles, then touch + time).

| touch | configuration | objects recompiled | wall time | log |
|---|---|---|---|---|
| `ColliderBit_rollcall.hpp` | legacy | 23 ColliderBit TUs + `gambit.cpp.o` + link | 9m22.5s | `touch_cb_legacy.log` |
| `ColliderBit_rollcall.hpp` | link-time | 23 ColliderBit TUs + `ColliderBit_registration.cpp.o` + link | 7m04.1s | `touch_cb_ltr.log` |
| `ExampleBit_A_rollcall.hpp` | legacy | `ExampleBit_A.cpp.o` + `gambit.cpp.o` + link | 4m56.5s | `touch_eba_legacy.log` |
| `ExampleBit_A_rollcall.hpp` | link-time | `ExampleBit_A.cpp.o` + `ExampleBit_A_registration.cpp.o` + link | 0m31.0s | `touch_eba_ltr.log` |

The ExampleBit_A rows show the cross-Bit isolation effect: in the legacy path,
adding a large Bit to the build makes every other Bit's rollcall edits pay that
Bit's share of the `gambit.cpp` recompile.

## Backends round

Same configuration and protocol; experiment:
`touch Backends/include/gambit/Backends/frontends/LibFirst_1_0.hpp && time make gambit`.

| configuration | objects recompiled | wall time | log |
|---|---|---|---|
| legacy | `gambit.cpp.o` + link | 4m32.2s | `touch_be_legacy.log` |
| link-time | `Backends_registration.cpp.o` + link | 0m55.2s | `touch_be_ltr.log` |

## All-Bits round

Configuration: all Bits (no `-DBits` restriction), `-DBUILD_FS_MODELS=None
-DWITH_HEPMC=ON -DWITH_YODA=OFF -DWITH_MPI=Off -DCMAKE_BUILD_TYPE=Release`,
same machine.  1654 module functors + 1610 backend functors registered;
module and backend functor tables byte-identical between the two
configurations, spartan smoke test passing in both.

| touch | configuration | objects recompiled | wall time | log |
|---|---|---|---|---|
| `DarkBit_rollcall.hpp` | legacy | 30 DarkBit TUs + `gambit.cpp.o` + link | 33m11.9s | `touch_db_legacy.log` |
| `DarkBit_rollcall.hpp` | link-time | 30 DarkBit TUs + `DarkBit_registration.cpp.o` + link | 9m47.1s | `touch_db_ltr.log` |
| `ExampleBit_A_rollcall.hpp` | legacy | `ExampleBit_A.cpp.o` + `gambit.cpp.o` + link | 25m41.4s | `touch_eba_legacy_all.log` |
| `ExampleBit_A_rollcall.hpp` | link-time | `ExampleBit_A.cpp.o` + `ExampleBit_A_registration.cpp.o` + link | 0m49.0s | `touch_eba_ltr_all.log` |
