//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  Likelihood-aware adaptive stopping of the
///  ColliderBit Monte Carlo event loop.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author Chris Chang
///  \date   2026 Oct
///
///  *********************************************

#include <algorithm>
#include <cmath>
#include <limits>

#include "gambit/ColliderBit/MC_adaptive_stopping.hpp"

namespace Gambit
{
  namespace ColliderBit
  {
    namespace AdaptiveStopping
    {

      /// Smallest Poisson mean allowed, to avoid log(0) (cf. the s=0.001 floor in LHC_likelihoods.cpp)
      static const double MU_FLOOR = 1e-9;

      double profiled_loglike(double n_obs, double mu, double sigma)
      {
        mu = std::max(mu, MU_FLOOR);

        // Without a nuisance this is a plain Poisson
        if (sigma <= 0) return n_obs * std::log(mu) - mu;

        // Maximise n ln(m) - m - (m-mu)^2/(2 sigma^2) over m > 0:
        // m^2 + a m - n sigma^2 = 0, with a = sigma^2 - mu.
        const double sig2 = sigma * sigma;
        const double a = sig2 - mu;
        const double disc = std::sqrt(a * a + 4 * n_obs * sig2);
        // Use the numerically stable form of the positive root
        double m = (a > 0) ? 2 * n_obs * sig2 / (a + disc) : (disc - a) / 2;
        m = std::max(m, MU_FLOOR);

        const double pull = m - mu;
        return n_obs * std::log(m) - m - pull * pull / (2 * sig2);
      }

      double delta_loglike(double n_obs, double s, double b, double b_err, double s_err)
      {
        const double sb_err = std::sqrt(b_err * b_err + s_err * s_err);
        return profiled_loglike(n_obs, s + b, sb_err) - profiled_loglike(n_obs, b, b_err);
      }

      std::pair<double,double> mc_count_interval(double n_mc, double z)
      {
        n_mc = std::max(n_mc, 0.0);
        const double half_width = z * std::sqrt(n_mc);
        // The extra z^2 keeps the upper edge sensible for small counts (n=0 -> z^2)
        return {std::max(0.0, n_mc - half_width), n_mc + half_width + z * z};
      }

      /// Expected signal events and their MC uncertainty for a given MC count
      static std::pair<double,double> signal_and_err(const SRCounts& sr, double n_mc)
      {
        return {sr.scale * n_mc, sr.scale * std::sqrt(n_mc + sr.n_mc_sys * sr.n_mc_sys)};
      }

      Bounds analysis_bounds(const std::vector<SRCounts>& srs, double z)
      {
        Bounds result;
        if (srs.empty()) return result;

        const size_t n_SR = srs.size();
        std::vector<double> exp_most_excl(n_SR), exp_least_excl(n_SR), obs_upper(n_SR);

        for (size_t i = 0; i < n_SR; ++i)
        {
          const SRCounts& sr = srs[i];
          const auto interval = mc_count_interval(sr.n_mc, z);
          const auto lo = signal_and_err(sr, interval.first);
          const auto hi = signal_and_err(sr, interval.second);

          // Expected (Asimov, n_obs = b) delta lnL decreases with s, so the interval edges bound it
          exp_most_excl[i]  = delta_loglike(sr.n_bkg, hi.first, sr.n_bkg, sr.n_bkg_err, hi.second);
          exp_least_excl[i] = delta_loglike(sr.n_bkg, lo.first, sr.n_bkg, sr.n_bkg_err, lo.second);

          // Observed delta lnL is unimodal in s: check both edges and the best-fit signal, if inside
          const double s_fit = std::min(std::max(sr.n_obs - sr.n_bkg, lo.first), hi.first);
          const double n_fit = (sr.scale > 0) ? s_fit / sr.scale : 0.0;
          const auto fit = signal_and_err(sr, n_fit);
          const double dl_lo  = delta_loglike(sr.n_obs, lo.first,  sr.n_bkg, sr.n_bkg_err, lo.second);
          const double dl_hi  = delta_loglike(sr.n_obs, hi.first,  sr.n_bkg, sr.n_bkg_err, hi.second);
          const double dl_fit = delta_loglike(sr.n_obs, fit.first, sr.n_bkg, sr.n_bkg_err, fit.second);

          obs_upper[i] = std::max({dl_lo, dl_hi, dl_fit});
          result.dlnL_abs += std::max({std::fabs(dl_lo), std::fabs(dl_hi), std::fabs(dl_fit)});
        }

        // SR i can still end up as the best expected SR if its most exclusive expected value
        // beats the least exclusive expected value of the current best SR.
        const double best_least_excl = *std::min_element(exp_least_excl.begin(), exp_least_excl.end());
        result.dlnL_upper = -std::numeric_limits<double>::infinity();
        for (size_t i = 0; i < n_SR; ++i)
        {
          if (exp_most_excl[i] <= best_least_excl) result.dlnL_upper = std::max(result.dlnL_upper, obs_upper[i]);
        }

        return result;
      }

    }
  }
}
