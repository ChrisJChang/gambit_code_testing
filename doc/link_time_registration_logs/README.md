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
