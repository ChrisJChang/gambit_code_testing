# ExampleBit_A

ExampleBit_A is GAMBIT's tutorial/example module. It does not compute any
real physics; instead, each capability is a small, self-contained
demonstration of a GAMBIT module-writing feature - declaring observables and
likelihoods, expressing dependencies, interacting with scan models, managing
event loops, retrieving backend function pointers, calling Fortran common
blocks via Farray overlays, and chaining capabilities recursively. New
GAMBIT module authors are meant to read this module's rollcall header and
source file side by side as a worked reference before writing their own
module.

Like other GAMBIT modules, ExampleBit_A exposes its functionality through
`CAPABILITY`/`FUNCTION` declarations (see
`include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp`); the diagram below
shows how those capabilities are chained together at runtime, with each node
annotated with the C++ return type declared in its `START_FUNCTION(...)`
macro, rather than the literal call graph.

## Pipeline overview

```mermaid
flowchart TD
    subgraph EventsDemo["Toy event-count pipeline"]
        Xsec["test_sigma<br/>capability: xsection<br/>returns: double"]
        NEvents["nevents_pred<br/>capability: nevents<br/>returns: double"]
        NEventsRounded["nevents_pred_rounded<br/>capability: nevents<br/>returns: int"]
    end

    subgraph LoopDemo["Loop-management demo: eventloop in ExampleBit_A.cpp"]
        LoopMgr["eventLoopManager<br/>capability: eventLoopManagement<br/>returns: void, CAN_MANAGE_LOOPS"]
        EventGen["exampleEventGen<br/>capability: event<br/>returns: float"]
        Cut["exampleCut<br/>capability: event<br/>returns: int"]
        Accum["eventAccumulator<br/>capability: eventAccumulation<br/>returns: int"]
    end

    subgraph LikeDemo["Toy likelihoods"]
        NEventsLike["nevents_like<br/>capability: Example_lnL_A<br/>returns: double"]
        GaussLike["lnL_gaussian<br/>capability: normaldist_loglike<br/>returns: double"]
        FlatLike["flat_likelihood<br/>capability: test_flat_likelihood<br/>returns: double"]
    end

    subgraph ModelDemo["Model-interaction demo"]
        Damu["example_damu<br/>capability: damu<br/>returns: double"]
        PID["particle_identity<br/>capability: particle_id<br/>returns: std::string"]
    end

    subgraph BackendDemo["Backend-interfacing demos"]
        FuncPtr["function_pointer_retriever<br/>capability: function_pointer<br/>returns: fptr"]
        Farray["do_Farray_stuff<br/>capability: test_Farrays<br/>returns: double"]
        MargPoisson["marg_poisson_test<br/>capability: test_marg_lnlike<br/>returns: double"]
        BEArray["Backend_array_test<br/>capability: test_BE_Array<br/>returns: double"]
    end

    subgraph MiscDemo["Misc testers: printer, recursion"]
        LargePrint["large_print<br/>capability: large_print<br/>returns: map_str_dbl"]
        StartVal["const_one<br/>capability: starting_value<br/>returns: int"]
        Recursive["recursive_add_1..4<br/>capability: recursive_sum<br/>returns: int"]
    end

    Xsec --> NEvents
    NEvents --> NEventsRounded
    NEvents --> NEventsLike
    LoopMgr --> EventGen
    EventGen --> Cut
    Cut --> Accum
    Accum --> NEventsLike
    StartVal --> Recursive
    Recursive --> Recursive
```

## Key source locations

| Stage | Key capability | Return type | Files |
|---|---|---|---|
| Toy cross-section / event-count pipeline | `xsection` / `nevents` | `double` / `int` | `include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp`, `src/ExampleBit_A.cpp` |
| Loop-management demo | `eventLoopManagement` / `event` / `eventAccumulation` | `void, CAN_MANAGE_LOOPS` / `float`,`int` / `int` | `include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp`, `src/ExampleBit_A.cpp` |
| Toy likelihoods | `Example_lnL_A` / `normaldist_loglike` / `test_flat_likelihood` | `double` | `include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp`, `src/ExampleBit_A.cpp` |
| Model-interaction demo | `damu` / `particle_id` | `double` / `std::string` | `include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp`, `src/ExampleBit_A.cpp` |
| Backend pointer/array/common-block demos | `function_pointer` / `test_Farrays` / `test_marg_lnlike` / `test_BE_Array` | `fptr` / `double` | `include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp`, `src/ExampleBit_A.cpp` |
| Printer-buffer stress test | `large_print` | `map_str_dbl` | `include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp`, `src/ExampleBit_A.cpp` |
| Recursive dependency-chain demo | `starting_value` / `recursive_sum` | `int` | `include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp`, `src/ExampleBit_A.cpp` |

This is a high-level pipeline view, not an exhaustive capability/function
reference - see `include/gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp` for
the full set of `CAPABILITY`/`FUNCTION` declarations and their dependency
requirements.
