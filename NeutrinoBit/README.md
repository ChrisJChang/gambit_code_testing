# NeutrinoBit

NeutrinoBit is the GAMBIT module responsible for neutrino physics. It
constructs the active-neutrino mass matrix and PMNS mixing matrix from a
given model point, derives oscillation parameters and mass-squared
splittings, and - for models with right-handed/sterile neutrinos - builds
the seesaw mixing/Theta matrix, the resulting heavy-neutrino active-flavour
mixings and decay widths, and combines all of this with experimental data
into log-likelihoods (oscillation global fits, neutrinoless double-beta
decay, BBN, peak-search and collider/beam-dump bounds on sterile neutrinos).

Like other GAMBIT modules, NeutrinoBit exposes its functionality through
`CAPABILITY`/`FUNCTION` declarations (see
`include/gambit/NeutrinoBit/NeutrinoBit_rollcall.hpp`); the diagram below
shows how those capabilities are chained together at runtime, with each
node annotated with the C++ return type declared in its `START_FUNCTION(...)`
macro, rather than the literal call graph.

## Pipeline overview

```mermaid
flowchart TD
    subgraph Input
        Model[Model point parameters]
    end

    subgraph MassMix["Mass matrix and mixing: NeutrinoBit_rollcall.hpp"]
        Ordering["ordering<br/>returns: bool"]
        Mnu["M_nu<br/>returns: Eigen::Matrix3cd"]
        UPMNS["UPMNS<br/>returns: Eigen::Matrix3cd"]
        Splittings["md21 / md31 / md32 / min_mass<br/>returns: double"]
    end

    subgraph Seesaw["Seesaw I parametrization"]
        Theta["SeesawI_Theta: CI_Theta<br/>returns: Eigen::Matrix3cd"]
        Vnu["SeesawI_Vnu: Vnu<br/>returns: Eigen::Matrix3cd"]
        UnitarityChk["Unitarity_UPMNS / Unitarity_SeesawI<br/>returns: bool"]
        Mixings["Ue1..Ut3, phases<br/>returns: double"]
    end

    subgraph Decays["Heavy neutrino decay widths: RightHandedNeutrinos.cpp"]
        Gammas["Gamma_RHN2piplusl, Gamma_RHN2Kplusl,<br/>Gamma_RHN2llnu, etc.<br/>returns: std::vector&lt;double&gt;"]
        GammaBBN["Gamma_BBN<br/>returns: std::vector&lt;double&gt;"]
        RW["R_W: RHN_R_W<br/>returns: std::vector&lt;double&gt;"]
        Rratios["R_pi / R_K / R_tau<br/>returns: double"]
    end

    subgraph OscLL["Oscillation likelihoods: NuFit comparisons"]
        ThetaLL["theta12/23/13_NuFit_v3_2_lnL,<br/>_v4_1_lnL<br/>returns: double"]
        DeltaLL["deltaCP_NuFit_v3_2_lnL,<br/>_v4_1_lnL<br/>returns: double"]
        MassLL["md21_NuFit, md3l_NuFit,<br/>md21_md3l_NuFit_v4_1_lnL<br/>returns: double"]
        SumMnuLL["sum_mnu_lnL<br/>returns: double"]
    end

    subgraph SterileLL["Sterile/RHN likelihoods"]
        BBNLL["lnL_bbn<br/>returns: double"]
        DBDLL["RHN_Thalf_0nubb_Xe / _Ge,<br/>RHN_mbb_0nubb_Xe / _Ge<br/>returns: double"]
        DBDComb["lnL_0nubb / lnL_mbb_0nubb<br/>returns: double"]
        RatioLL["lnL_R_K / lnL_R_pi /<br/>lnL_R_tau / lnL_R_W<br/>returns: double"]
        CKMLL["lnL_ckm_Vusmin / lnL_ckm_Vus<br/>returns: double"]
        SearchLL["lnL_pienu, lnL_ps191_e/mu,<br/>lnL_charm_e/mu/tau,<br/>lnL_delphi_short/long_lived,<br/>lnL_atlas_e/mu, lnL_e949,<br/>lnL_nutev, lnL_lhc_e/mu<br/>returns: double"]
        PerturbLL["perturbativity_likelihood<br/>returns: double"]
        CouplingSlide["coupling_slide<br/>returns: double"]
    end

    Model --> Ordering
    Ordering --> Mnu
    Mnu --> Splittings
    Ordering --> Splittings
    Model --> UPMNS
    Mnu --> Theta
    UPMNS --> Theta
    Theta --> Vnu
    UPMNS --> Vnu
    UPMNS --> UnitarityChk
    Mnu --> UnitarityChk
    Theta --> UnitarityChk
    Vnu --> UnitarityChk
    Theta --> Mixings

    Mixings --> Gammas
    Theta --> Gammas
    Gammas --> GammaBBN
    GammaBBN --> BBNLL
    RW --> Rratios
    Theta --> Rratios
    Vnu --> Rratios
    Rratios --> RatioLL
    RW --> RatioLL

    Model --> ThetaLL
    Ordering --> ThetaLL
    Model --> DeltaLL
    Ordering --> DeltaLL
    Splittings --> MassLL
    Ordering --> MassLL
    Model --> SumMnuLL

    Mnu --> DBDLL
    UPMNS --> DBDLL
    Theta --> DBDLL
    DBDLL --> DBDComb

    Theta --> CKMLL

    Mixings --> SearchLL

    Theta --> PerturbLL
    Mixings --> CouplingSlide
    Theta --> CouplingSlide
```

## Key source locations

| Stage | Key capability | Return type | Files |
|---|---|---|---|
| Mass matrix / ordering | `ordering` / `m_nu` | `bool` / `Eigen::Matrix3cd` | `include/gambit/NeutrinoBit/NeutrinoBit_rollcall.hpp`, `src/NeutrinoBit.cpp` |
| Mass splittings | `md21` / `md31` / `md32` / `min_mass` | `double` | same as above |
| PMNS mixing matrix | `UPMNS` | `Eigen::Matrix3cd` | `include/gambit/NeutrinoBit/NeutrinoBit_rollcall.hpp`, `src/NeutrinoBit.cpp` |
| Seesaw I parametrization | `SeesawI_Theta` / `SeesawI_Vnu` | `Eigen::Matrix3cd` | `include/gambit/NeutrinoBit/NeutrinoBit_rollcall.hpp`, `src/RightHandedNeutrinos.cpp` |
| Unitarity checks | `Unitarity_UPMNS` / `Unitarity_SeesawI` | `bool` | `src/RightHandedNeutrinos.cpp` |
| Heavy-light flavour mixings | `Ue1`..`Ut3` and phases | `double` | `src/RightHandedNeutrinos.cpp` |
| RHN partial decay widths | `Gamma_RHN2piplusl`, `Gamma_RHN2llnu`, etc. | `std::vector<double>` | `src/RightHandedNeutrinos.cpp` |
| BBN constraint | `Gamma_BBN` / `lnL_bbn` | `std::vector<double>` / `double` | `src/RightHandedNeutrinos.cpp` |
| Meson decay ratios | `R_pi` / `R_K` / `R_tau` / `R_W` | `double` / `std::vector<double>` | `src/RightHandedNeutrinos.cpp` |
| Neutrinoless double-beta decay | `RHN_Thalf_0nubb_Xe` / `_Ge`, `RHN_mbb_0nubb_Xe` / `_Ge` | `double` | `src/RightHandedNeutrinos.cpp` |
| 0nubb combined likelihoods | `lnL_0nubb` / `lnL_mbb_0nubb` | `double` | `src/RightHandedNeutrinos.cpp` |
| CKM unitarity / Vus | `calc_Vus`, `lnL_ckm_Vusmin`, `lnL_ckm_Vus` | `double` | `src/RightHandedNeutrinos.cpp` |
| Beam-dump / collider peak searches | `lnL_pienu`, `lnL_ps191_e`/`_mu`, `lnL_charm_e`/`_mu`/`_tau`, `lnL_delphi_short_lived`/`_long_lived`, `lnL_atlas_e`/`_mu`, `lnL_e949`, `lnL_nutev`, `lnL_lhc_e`/`_mu` | `double` | `src/RightHandedNeutrinos.cpp` |
| Theory consistency | `perturbativity_likelihood`, `coupling_slide` | `double` | `src/RightHandedNeutrinos.cpp` |
| Oscillation global-fit likelihoods | `theta12`/`theta23`/`theta13`/`deltaCP`_NuFit_v3_2_lnL / _v4_1_lnL, `md21`/`md3l`_NuFit_lnL, `sum_mnu_lnL` | `double` | `include/gambit/NeutrinoBit/NeutrinoBit_rollcall.hpp`, `src/NeutrinoBit.cpp`, `include/gambit/NeutrinoBit/NeutrinoInterpolator.hpp` |

This is a high-level pipeline view, not an exhaustive capability/function
reference — see `NeutrinoBit_rollcall.hpp` for the full set of
`CAPABILITY`/`FUNCTION` declarations and their dependency requirements.
