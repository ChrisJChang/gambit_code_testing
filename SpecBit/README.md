# SpecBit

SpecBit is the GAMBIT module responsible for generating particle mass
spectra for a given model point. It links model input parameters to
spectrum-generator backends (FlexibleSUSY, SPheno, SoftSUSY, SUSYHD,
FeynHiggs, etc.), wraps the results in GAMBIT's standard `Spectrum`
object, and derives quantities such as precision Higgs masses, Higgs
couplings, and electroweak/high-scale vacuum stability from those
spectra. Almost every other module that needs particle masses, mixings,
or decay information ultimately depends on a `Spectrum` object produced
by SpecBit.

Like other GAMBIT modules, SpecBit exposes its functionality through
`CAPABILITY`/`FUNCTION` declarations (see `include/gambit/SpecBit/*_rollcall.hpp`);
the diagram below shows how those capabilities are chained together at
runtime, with each node annotated with the C++ return type declared in its
`START_FUNCTION(...)` macro, rather than the literal call graph.

## Pipeline overview

```mermaid
flowchart TD
    subgraph Input
        Model[Model point parameters]
        SMI["SMINPUTS<br/>returns: SMInputs"]
    end

    subgraph SpecGen["Spectrum generation: SpecBit_MSSM_rollcall.hpp, SpecBit_SM_rollcall.hpp, model rollcalls"]
        MSSMSpec["get_MSSMatQ_spectrum_FS / get_CMSSM_spectrum_FS /<br/>get_MSSM_spectrum_SPheno<br/>returns: Spectrum"]
        SMSpec["get_SM_spectrum<br/>returns: Spectrum"]
        DMSpec["get_ScalarSingletDM_Z2_spectrum /<br/>get_DMEFT_spectrum / get_MDM_spectrum, etc.<br/>returns: Spectrum"]
        QedQcd["get_QedQcd_spectrum<br/>returns: const SubSpectrum pointer"]
    end

    subgraph Improve["Improvement and conversion: SpecBit.cpp, SpecBit_rollcall.hpp"]
        ImprovedMSSM["MSSM_spectrum:<br/>improve unimproved_MSSM_spectrum<br/>returns: Spectrum"]
        ConvertSM["convert_MSSM_to_SM /<br/>convert_NMSSM_to_SM<br/>returns: Spectrum"]
        SLHAout["get_MSSM_spectrum_as_SLHAea_SLHA1/2<br/>returns: SLHAstruct"]
        MapOut["get_MSSM_spectrum_as_map /<br/>get_ScalarSingletDM_Z2_spectrum_as_map<br/>returns: map_str_dbl"]
    end

    subgraph Precision["Precision observables: SpecBit_MSSM.cpp, FeynHiggs/SUSYHD backends"]
        HiggsMasses["FeynHiggs_AllHiggsMasses<br/>returns: fh_HiggsMassObs_container"]
        PrecMh["FeynHiggs_HiggsMass / SUSYHD_HiggsMass<br/>returns: triplet of double"]
        HeavyHiggs["FeynHiggs_HeavyHiggsMasses<br/>returns: map_int_triplet_dbl"]
        Couplings["MSSM_higgs_couplings_pwid /<br/>MSSM_higgs_couplings_FeynHiggs<br/>returns: HiggsCouplingsTable"]
    end

    subgraph Vacuum["Vacuum stability: SpecBit_VS_rollcall.hpp, Vevacious backend"]
        VacInfo["find_min_lambda_ScalarSingletDM_Z2/Z3<br/>returns: dbl_dbl_bool"]
        PassVev["prepare_pass_MSSM_spectrum_to_vevacious<br/>returns: SpectrumEntriesForVevacious"]
        CheckVac["check_vacuum_stability_vevacious<br/>returns: VevaciousResultContainer"]
        VSLogLike["get_likelihood_VS<br/>returns: double"]
        EWVac["check_EW_stability_ScalarSingletDM_Z3<br/>returns: double"]
    end

    Model --> MSSMSpec
    Model --> SMSpec
    Model --> DMSpec
    SMI --> MSSMSpec
    SMI --> SMSpec
    SMI --> DMSpec
    SMI --> QedQcd

    MSSMSpec --> ImprovedMSSM
    ImprovedMSSM --> ConvertSM
    ImprovedMSSM --> SLHAout
    ImprovedMSSM --> MapOut
    DMSpec --> MapOut

    ImprovedMSSM --> HiggsMasses
    HiggsMasses --> PrecMh
    ImprovedMSSM --> PrecMh
    HiggsMasses --> HeavyHiggs
    ImprovedMSSM --> HeavyHiggs
    ImprovedMSSM --> Couplings

    DMSpec --> VacInfo
    ImprovedMSSM --> PassVev
    PassVev --> CheckVac
    CheckVac --> VSLogLike
    DMSpec --> EWVac
```

## Key source locations

| Stage | Key capability | Return type | Files |
|---|---|---|---|
| SM inputs | `SMINPUTS` | `SMInputs` | `include/gambit/SpecBit/SpecBit_SM_rollcall.hpp`, `src/SpecBit_SM.cpp` |
| MSSM spectrum generation | `unimproved_MSSM_spectrum` | `Spectrum` | `include/gambit/SpecBit/SpecBit_MSSM_rollcall.hpp`, `src/SpecBit_MSSM.cpp`, `src/MSSMspec.cpp` |
| SM spectrum generation | `SM_spectrum` | `Spectrum` | `include/gambit/SpecBit/SpecBit_SM_rollcall.hpp`, `src/SpecBit_SM.cpp`, `src/QedQcdWrapper.cpp` |
| BSM/DM model spectra | `ScalarSingletDM_Z2_spectrum` / `VectorSingletDM_Z2_spectrum` / `DMEFT_spectrum` / `MDM_spectrum` (representative) | `Spectrum` | `include/gambit/SpecBit/SpecBit_ScalarSingletDM_rollcall.hpp`, `SpecBit_VectorSingletDM_rollcall.hpp`, `SpecBit_DMEFT_rollcall.hpp`, `SpecBit_MDM_rollcall.hpp`, corresponding `src/SpecBit_*.cpp` |
| Spectrum improvement/conversion | `MSSM_spectrum` / `SM_spectrum` via `convert_MSSM_to_SM` | `Spectrum` | `include/gambit/SpecBit/SpecBit_rollcall.hpp`, `src/SpecBit.cpp` |
| Spectrum serialisation | `get_MSSM_spectrum_as_SLHAea_SLHA1` / `_SLHA2` | `SLHAstruct` | `include/gambit/SpecBit/SpecBit_MSSM_rollcall.hpp`, `src/SpecBit_MSSM.cpp` |
| Spectrum printing | `get_MSSM_spectrum_as_map` / `get_ScalarSingletDM_Z2_spectrum_as_map` | `map_str_dbl` | `include/gambit/SpecBit/SpecBit_MSSM_rollcall.hpp`, `SpecBit_ScalarSingletDM_rollcall.hpp` |
| Precision Higgs mass | `prec_mh` (`FeynHiggs_HiggsMass` / `SUSYHD_HiggsMass`) | `triplet<double>` | `include/gambit/SpecBit/SpecBit_MSSM_rollcall.hpp`, `src/SpecBit_MSSM.cpp` |
| Higgs mass/coupling backends | `HiggsMasses` / `Higgs_Couplings` | `fh_HiggsMassObs_container` / `HiggsCouplingsTable` | `include/gambit/SpecBit/SpecBit_MSSM_rollcall.hpp`, `SpecBit_SM_rollcall.hpp`, `SpecBit_ScalarSingletDM_rollcall.hpp` |
| Vacuum stability (analytic) | `high_scale_vacuum_info` / `lnL_EW_vacuum` | `dbl_dbl_bool` / `double` | `include/gambit/SpecBit/SpecBit_VS_rollcall.hpp`, `src/SpecBit_VS.cpp` |
| Vacuum stability (Vevacious) | `check_vacuum_stability` / `VS_likelihood` | `VevaciousResultContainer` / `double` | `include/gambit/SpecBit/SpecBit_VS_rollcall.hpp`, `src/SpecBit_VS.cpp` |

This is a high-level pipeline view, not an exhaustive capability/function
reference — see the `*_rollcall.hpp` headers for the full set of
`CAPABILITY`/`FUNCTION` declarations and their dependency requirements.
