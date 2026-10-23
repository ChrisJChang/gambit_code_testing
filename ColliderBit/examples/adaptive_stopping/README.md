# Likelihood-aware adaptive MC event counts in ColliderBit

By default ColliderBit generates a fixed number of Pythia events per parameter point
(16M in `yaml_files/SUSYRun2_MSSMEW.yaml`). With `adaptive_stopping`, the event loop
checks the LHC likelihood at geometric checkpoints and stops early when a point is
either **decisively excluded** or **insensitive** to the LHC searches.

**This is for frequentist (profile-likelihood) scans only.** The stopping rule depends
on the generated events, so the resulting likelihood is not an unbiased estimator.
Do not use it with nested sampling or MCMC.

## The stopping rule

At each checkpoint `N = adaptive_first_check * adaptive_growth^k < max_nEvents`, and for
every signal region (SR):

1. The accepted MC count `n` gives a z-sigma interval on its true mean,
   `[n - z sqrt(n), n + z sqrt(n) + z^2]`. Here z is `adaptive_n_sigma_MC`, and the
   `z^2` keeps the upper edge non-zero when `n = 0`.
2. The interval is scaled to expected signal events with `xsec * lumi / N`. The
   cross-section is `InitialTotalCrossSection`.
3. `dlnL = lnL(s+b) - lnL(b)` is evaluated with a Poisson likelihood and a profiled
   Gaussian uncertainty, `b_err` for b-only and `sqrt(b_err^2 + s_err^2)` for s+b. This
   is the same structure as `calc_LHC_LogLikes`.
4. **Per analysis:** only SRs that could still become the "best expected" SR at full
   statistics are kept. The optimistic bound `dlnL_upper` is the largest observed
   `dlnL` over those SRs and over the signal interval.
5. **Combined:** the bounds are summed over analyses and over all analysis containers
   (ATLAS, CMS, ...), as `LHC_Combined_LogLike` does. `Baselines` and the analyses in
   `adaptive_ignore_analyses` are left out.

The loop stops if `dlnL_upper < -adaptive_delta_lnL_threshold` (excluded) or if the
summed bound on `|dlnL|` is below `adaptive_insensitive_delta_lnL` (insensitive).
Points that could be near the best fit or a confidence contour run to `max_nEvents`.

Limitations:
- For analyses with SR covariances, the per-SR bound approximates the full
  covariance combination; it is not a strict bound.
- The cross-section comes from the initial Pythia estimate (10k events in the
  SUSYRun2 yaml), not the final event-generation one.
- `adaptive_delta_lnL_threshold` is measured relative to b-only, not to the scan's
  best fit. This suits SUSYRun2, whose best fit is close to b-only.

The `adaptive_log_only` runs below measure the effect of all three limitations directly.

## YAML options (under the collider block of `RunMC`)

| option | default | meaning |
|---|---|---|
| `adaptive_stopping` | `false` | enable the checks (needs `max_nEvents`, not UMVUE) |
| `adaptive_log_only` | `false` | evaluate and record the decision, but never stop |
| `adaptive_first_check` | `250000` | events before the first checkpoint |
| `adaptive_growth` | `2.0` | factor between checkpoints |
| `adaptive_delta_lnL_threshold` | `15` | T: stop if the optimistic LHC dlnL < -T |
| `adaptive_n_sigma_MC` | `3` | z for the MC-count interval |
| `adaptive_insensitive_delta_lnL` | `0.1` | stop if the summed bound on \|dlnL\| is below this |
| `adaptive_ignore_analyses` | `[]` | analyses left out (keep in sync with `skip_analyses`) |

Per-point diagnostics are added to the `LHCEventLoopInfo` observable, with keys suffixed
by the collider name:
- `adaptive_n_checkpoints`
- `adaptive_stop_reason` (0 none, 1 excluded, 2 insensitive)
- `adaptive_events_at_stop` (-1 if never met)
- `adaptive_dlnL_upper_at_stop`, `adaptive_dlnL_abs_at_stop`
- `adaptive_dlnL_upper_latest`, `adaptive_dlnL_abs_latest`

## Running the paired study on a cluster

1. Build GAMBIT without the LHC measurements:
   ```
   cmake -Ditch="rivet;contur;<anything else you do not need>" -DBUILD_FS_MODELS="MSSM_mAmu" ..
   make -jN gambit
   ```
   ColliderBit still compiles the BOSSed Rivet type headers, so YODA headers must be
   available (`make yoda`). The full Rivet build is not needed.
2. Run both scans with the same MPI/OpenMP layout and wall-time allocation:
   ```
   mpirun -n <ranks> ./gambit -f yaml_files/SUSYRun2_MSSMEW_fixedN.yaml
   mpirun -n <ranks> ./gambit -f yaml_files/SUSYRun2_MSSMEW_adaptive.yaml
   ```
   The two files differ only in `adaptive_log_only` and the output file name. Both use
   a fixed Diver seed and print per-function runtimes (`print_timing_data: true`).
   The fixed-N run (log-only) is also the dataset for tuning T and z offline.
3. Compare:
   ```
   ColliderBit/examples/adaptive_stopping/compare_adaptive_scans.py \
       runs/SUSYRun2_MSSMEW_fixedN/samples/SUSYRun2_MSSMEW_fixedN.hdf5 \
       runs/SUSYRun2_MSSMEW_adaptive/samples/SUSYRun2_MSSMEW_adaptive.hdf5 \
       --x M2 --y mu --outdir plots
   ```
   The script reports:
   - Cost: events and `operateLHCLoop` runtime per point, and the speedup.
   - Fidelity: from the fixed-N log-only decisions, how many stops would have hit
     points inside the region of interest, or broken the bound.
   - Best fits and the overlap of the 2D 1σ/2σ regions.

   Optionally, rerun a sample of the adaptive scan's early-stopped points at full
   statistics with the postprocessor scanner.

## Standalone test of the statistics

```
g++ -O2 -std=c++17 -IColliderBit/include ColliderBit/examples/adaptive_stopping/test_adaptive_stopping.cpp \
    ColliderBit/src/MC_adaptive_stopping.cpp -o test_adaptive_stopping && ./test_adaptive_stopping
```
It checks the analytic profiling against brute force and the coverage of the upper
bound on toy analyses.
