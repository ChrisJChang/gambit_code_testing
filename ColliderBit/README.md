# ColliderBit

ColliderBit is the GAMBIT module responsible for computing collider
(mainly LHC and LEP) likelihoods for a given model point. It drives Monte
Carlo event generation, detector simulation, signal-region/analysis
recasting, and combines the results into log-likelihoods that feed back
into the GAMBIT scan.

Like other GAMBIT modules, ColliderBit exposes its functionality through
`CAPABILITY`/`FUNCTION` declarations (see `include/gambit/ColliderBit/*_rollcall.hpp`);
the diagram below shows how those capabilities are chained together at
runtime rather than the literal call graph.

## Pipeline overview

```mermaid
flowchart TD
    subgraph Input
        Model[Model point parameters]
    end

    subgraph "Cross sections (ColliderBit_MC_rollcall.hpp)"
        XS[InitialTotalCrossSection /\nInitialProcessCrossSections]
        ActiveProc[ActiveProcessCodes /\nActivePIDPairs]
    end

    subgraph "MC event loop (ColliderBit_eventloop.cpp/.hpp)"
        Collider[getPy8Collider:\nconfigure Pythia8 collider]
        RunMC[RunMC:\nMCLoopInfo loop manager]
        GenEvent[generateEventPy8Collider /\ngetLHEvent:\nevent generation]
        Detector[Detector simulation\n(src/detectors, getBuckFast,\nsmearEvent, ATLAS/CMS efficiencies)]
    end

    subgraph "Analyses (src/analyses)"
        RunAnalyses[runAnalyses:\nsignal-region recasting]
        Rivet[Rivet_measurements\n(ColliderBit_measurements_rollcall.hpp)]
    end

    subgraph "Likelihoods"
        XsecConsistency[CrossSectionConsistencyCheck]
        LHCLogLike[LHC_measurements_LogLike /\nLogLike_Multi / LogLike_perPool]
        LEPLogLike[LEP likelihoods\n(ColliderBit_LEP_rollcall.hpp)]
        HiggsLogLike[Higgs likelihoods\n(ColliderBit_Higgs_rollcall.hpp)]
    end

    Output[Combined ColliderBit LogLike\n-> GAMBIT total likelihood]

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

| Stage | Files |
|---|---|
| Cross sections | `include/gambit/ColliderBit/ColliderBit_MC_rollcall.hpp`, `src/xsec.cpp`, `src/getxsec.cpp` |
| Collider/event-loop setup | `include/gambit/ColliderBit/ColliderBit_eventloop.hpp`, `src/ColliderBit_eventloop.cpp`, `include/gambit/ColliderBit/getPy8Collider.hpp` |
| Event generation | `include/gambit/ColliderBit/generateEventPy8Collider.hpp`, `src/getHepMCEvent.cpp`, `src/getLHEvent.cpp`, `src/lhef2heputils.cpp` |
| Detector simulation | `src/detectors/`, `src/getBuckFast.cpp`, `src/smearEvent.cpp`, `include/gambit/ColliderBit/ATLASEfficiencies.hpp`, `CMSEfficiencies.hpp` |
| Analyses / recasting | `src/analyses/`, `src/runAnalyses.cpp`, `src/getAnalysisContainer.cpp` |
| Measurements (Rivet/Contur) | `include/gambit/ColliderBit/ColliderBit_measurements_rollcall.hpp`, `src/ColliderBit_measurements.cpp` |
| LEP likelihoods | `include/gambit/ColliderBit/ColliderBit_LEP_rollcall.hpp`, `src/ColliderBit_LEP.cpp`, `src/lep_mssm_xsecs.cpp` |
| Higgs likelihoods | `include/gambit/ColliderBit/ColliderBit_Higgs_rollcall.hpp`, `src/ColliderBit_Higgs.cpp` |
| MC convergence/loop control | `include/gambit/ColliderBit/MCLoopInfo.hpp`, `MC_convergence.hpp`, `src/MCLoopInfo.cpp`, `src/MC_convergence.cpp` |

This is a high-level pipeline view, not an exhaustive capability/function
reference — see the `*_rollcall.hpp` headers for the full set of
`CAPABILITY`/`FUNCTION` declarations and their dependency requirements.
