//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  Likelihood-aware adaptive stopping of the
///  ColliderBit Monte Carlo event loop.
///
///  At each checkpoint of the event loop, the
///  signal MC counts are turned into conservative
///  bounds on the LHC delta log-likelihood
///  (s+b vs b-only). The loop can then be stopped
///  early for points that are either decisively
///  excluded or insensitive to the LHC searches.
///
///  Intended for frequentist (profile-likelihood)
///  scans only: the data-dependent stopping rule
///  does not give an unbiased likelihood estimator.
///
///  This header is free of GAMBIT dependencies so
///  that the statistics can be tested standalone.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author Chris Chang
///  \date   2026 Oct
///
///  *********************************************

#pragma once

#include <utility>
#include <vector>

namespace Gambit
{
  namespace ColliderBit
  {
    namespace AdaptiveStopping
    {

      /// Inputs for one signal region at a given point in the event loop
      struct SRCounts
      {
        double n_obs;      ///< Observed events
        double n_bkg;      ///< Expected background events
        double n_bkg_err;  ///< Absolute background uncertainty
        double n_mc;       ///< Accepted signal MC events so far (all threads)
        double n_mc_sys;   ///< Absolute signal MC systematic (MC-count units)
        double scale;      ///< xsec * lumi / N_generated: MC events -> expected signal events
      };

      /// Bounds on the delta log-likelihood of one analysis or a set of analyses
      struct Bounds
      {
        double dlnL_upper = 0.0;  ///< Optimistic (upper) bound on lnL_sb - lnL_b
        double dlnL_abs   = 0.0;  ///< Bound on |lnL_sb - lnL_b|, used for the insensitivity test
      };

      /// Poisson log-likelihood with a Gaussian nuisance on the mean, profiled analytically.
      /// The constant -ln(n_obs!) is dropped.
      double profiled_loglike(double n_obs, double mu, double sigma);

      /// lnL(s+b) - lnL(b) for a single SR, with the signal uncertainty added
      /// in quadrature to the background uncertainty for the s+b hypothesis,
      /// as in the full ColliderBit likelihood.
      double delta_loglike(double n_obs, double s, double b, double b_err, double s_err);

      /// Conservative z-sigma interval on the true mean of a Poisson MC count.
      /// The upper edge stays non-zero for zero observed counts.
      std::pair<double,double> mc_count_interval(double n_mc, double z);

      /// Bounds for one analysis. The SRs that could become the "best expected" SR
      /// at full statistics are kept as candidates; the upper bound is the most
      /// optimistic observed delta lnL among them.
      Bounds analysis_bounds(const std::vector<SRCounts>& srs, double z);

    }
  }
}
