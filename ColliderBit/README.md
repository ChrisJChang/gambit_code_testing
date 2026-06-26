# ColliderBit

ColliderBit is the GAMBIT module responsible for computing collider
(mainly LHC and LEP) likelihoods for a given model point. It drives Monte
Carlo event generation, detector simulation, signal-region/analysis
recasting, and combines the results into log-likelihoods that feed back
into the GAMBIT scan.

Like other GAMBIT modules, ColliderBit exposes its functionality through
`CAPABILITY`/`FUNCTION` declarations (see `include/gambit/ColliderBit/*_rollcall.hpp`);
the diagram below shows how those capabilities are chained together at
runtime, with each node annotated with the C++ return type declared in its
`START_FUNCTION(...)` macro, rather than the literal call graph.

## Pipeline overview

```mermaid
flowchart TD
    subgraph Input
        Model[Model point parameters]
    end

    subgraph CrossSec["Cross sections: ColliderBit_MC_rollcall.hpp"]
        XS["InitialTotalCrossSection<br/>returns: map_str_xsec_container<br/>InitialProcessCrossSections<br/>returns: map_str_map_int_process_xsec"]
        ActiveProc["ActiveProcessCodes<br/>returns: std::vector&lt;int&gt;<br/>ActivePIDPairs<br/>returns: vec_PID_pair"]
    end

    subgraph MCLoop["MC event loop: ColliderBit_eventloop.cpp/.hpp"]
        Collider["getPy8Collider:<br/>configure Pythia8 collider<br/>returns: void, fills Py8Collider&lt;...&gt;&amp; result"]
        RunMC["RunMC<br/>returns: MCLoopInfo"]
        GenEvent["generateEventPy8Collider /<br/>getLHEvent: event generation<br/>returns: HEPUtils::Event"]
        Detector["Detector simulation:<br/>src/detectors, getBuckFast,<br/>smearEvent, ATLAS/CMS efficiencies<br/>returns: BaseDetector* / HEPUtils::Event"]
    end

    subgraph Analyses["Analyses: src/analyses"]
        RunAnalyses["runAnalyses:<br/>signal-region recasting<br/>returns: AnalysisContainer / AnalysisDataPointers"]
        Rivet["Rivet_measurements:<br/>ColliderBit_measurements_rollcall.hpp<br/>returns: std::shared_ptr&lt;std::ostringstream&gt;"]
    end

    subgraph LL["Likelihoods"]
        XsecConsistency["CrossSectionConsistencyCheck<br/>returns: bool"]
        LHCLogLike["LHC_measurements_LogLike<br/>returns: double<br/>LHC_measurements_LogLike_Multi<br/>returns: map_str_dbl"]
        LEPLogLike["LEP likelihoods:<br/>ColliderBit_LEP_rollcall.hpp<br/>returns: triplet&lt;double&gt; - xsec, +/- error"]
        HiggsLogLike["LEP_Higgs_LogLike /<br/>LHC_Higgs_LogLike<br/>returns: double"]
    end

    Output["LHC_Combined_LogLike<br/>returns: double<br/>feeds GAMBIT total likelihood"]

    Model --> XS
    Model --> Collider
    XS --> ActiveProc
    ActiveProc --> RunMC
    Collider --> RunMC
    RunMC --> GenEvent
    GenEvent --> Detector
    Detector --> RunAnalyses
    RunAnalyses --> Rivet
    RunAnalyses --> LHCLogLike
    XS --> XsecConsistency
    XsecConsistency --> LHCLogLike
    Rivet --> LHCLogLike
    Model --> LEPLogLike
    Model --> HiggsLogLike
    LHCLogLike --> Output
    LEPLogLike --> Output
    HiggsLogLike --> Output
```

## Key source locations

| Stage | Key capability | Return type | Files |
|---|---|---|---|
| Cross sections | `InitialTotalCrossSection` | `map_str_xsec_container` | `include/gambit/ColliderBit/ColliderBit_MC_rollcall.hpp`, `src/xsec.cpp`, `src/getxsec.cpp` |
| Cross sections | `ActiveProcessCodes` | `std::vector<int>` | same as above |
| Collider/event-loop setup | `RunMC` | `MCLoopInfo` | `include/gambit/ColliderBit/ColliderBit_eventloop.hpp`, `src/ColliderBit_eventloop.cpp`, `include/gambit/ColliderBit/getPy8Collider.hpp` |
| Event generation | `HardScatteringEvent` | `HEPUtils::Event` / `HepMC3::GenEvent` | `include/gambit/ColliderBit/generateEventPy8Collider.hpp`, `src/getHepMCEvent.cpp`, `src/getLHEvent.cpp`, `src/lhef2heputils.cpp` |
| Detector simulation | `ATLASDetectorSim` / `ATLASSmearedEvent` | `BaseDetector*` / `HEPUtils::Event` | `src/detectors/`, `src/getBuckFast.cpp`, `src/smearEvent.cpp`, `include/gambit/ColliderBit/ATLASEfficiencies.hpp`, `CMSEfficiencies.hpp` |
| Analyses / recasting | `ATLASAnalysisContainer` / `AllAnalysisNumbers` | `AnalysisContainer` / `AnalysisDataPointers` | `src/analyses/`, `src/runAnalyses.cpp`, `src/getAnalysisContainer.cpp` |
| Measurements (Rivet/Contur) | `Rivet_measurements` / `LHC_measurements` | `std::shared_ptr<std::ostringstream>` / `Contur_output` | `include/gambit/ColliderBit/ColliderBit_measurements_rollcall.hpp`, `src/ColliderBit_measurements.cpp` |
| LEP likelihoods | `LEP207_xsec_chi00_11` (representative) | `triplet<double>` | `include/gambit/ColliderBit/ColliderBit_LEP_rollcall.hpp`, `src/ColliderBit_LEP.cpp`, `src/lep_mssm_xsecs.cpp` |
| Higgs likelihoods | `LEP_Higgs_LogLike` / `LHC_Higgs_LogLike` | `double` | `include/gambit/ColliderBit/ColliderBit_Higgs_rollcall.hpp`, `src/ColliderBit_Higgs.cpp` |
| Combined LHC likelihood | `LHC_Combined_LogLike` | `double` | `include/gambit/ColliderBit/ColliderBit_MC_rollcall.hpp` |
| MC convergence/loop control | `MCLoopInfo` | `MCLoopInfo` | `include/gambit/ColliderBit/MCLoopInfo.hpp`, `MC_convergence.hpp`, `src/MCLoopInfo.cpp`, `src/MC_convergence.cpp` |

This is a high-level pipeline view, not an exhaustive capability/function
reference — see the `*_rollcall.hpp` headers for the full set of
`CAPABILITY`/`FUNCTION` declarations and their dependency requirements.
