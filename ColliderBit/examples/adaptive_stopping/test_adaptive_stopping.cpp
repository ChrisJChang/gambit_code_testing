// Standalone tests for ColliderBit/src/MC_adaptive_stopping.cpp (no GAMBIT build needed).
//
// Build and run from the GAMBIT root directory:
//   g++ -O2 -std=c++17 -IColliderBit/include ColliderBit/examples/adaptive_stopping/test_adaptive_stopping.cpp
//       ColliderBit/src/MC_adaptive_stopping.cpp -o test_adaptive_stopping && ./test_adaptive_stopping

#include <cmath>
#include <cstdio>
#include <random>
#include <vector>

#include "gambit/ColliderBit/MC_adaptive_stopping.hpp"

using namespace Gambit::ColliderBit::AdaptiveStopping;

static int n_failed = 0;

static void check(bool ok, const char* what)
{
  std::printf("[%s] %s\n", ok ? " OK " : "FAIL", what);
  if (!ok) ++n_failed;
}

/// Brute-force maximisation of the profiled likelihood, for comparison
static double brute_profiled_loglike(double n, double mu, double sigma)
{
  double best = -1e300;
  const double lo = 1e-9, hi = std::max(mu, n) + 10 * sigma + 10;
  for (int i = 0; i <= 2000000; ++i)
  {
    const double m = lo + (hi - lo) * i / 2000000.0;
    best = std::max(best, n * std::log(m) - m - (m - mu) * (m - mu) / (2 * sigma * sigma));
  }
  return best;
}

/// A toy analysis: per-SR acceptance, observed and background numbers
struct ToySR { double acc, n_obs, n_bkg, n_bkg_err; };

/// Bounds after generating n_gen events for a toy analysis with cross-section*lumi = xsec_lumi
static Bounds toy_bounds(const std::vector<ToySR>& toy, double xsec_lumi, long n_gen, double z, std::mt19937_64& rng)
{
  std::vector<SRCounts> srs;
  for (const auto& sr : toy)
  {
    std::binomial_distribution<long> draw(n_gen, sr.acc);
    srs.push_back({sr.n_obs, sr.n_bkg, sr.n_bkg_err, double(draw(rng)), 0.0, xsec_lumi / n_gen});
  }
  return analysis_bounds(srs, z);
}

/// "True" delta lnL at infinite MC statistics: best expected SR, then its observed value
static double toy_true_dlnL(const std::vector<ToySR>& toy, double xsec_lumi)
{
  double best_exp = 1e300, result = 0;
  for (const auto& sr : toy)
  {
    const double s = sr.acc * xsec_lumi;
    const double e = delta_loglike(sr.n_bkg, s, sr.n_bkg, sr.n_bkg_err, 0.0);
    if (e < best_exp) { best_exp = e; result = delta_loglike(sr.n_obs, s, sr.n_bkg, sr.n_bkg_err, 0.0); }
  }
  return result;
}

int main()
{
  // 1. Profiled likelihood
  check(std::fabs(profiled_loglike(7, 5.0, 0.0) - (7 * std::log(5.0) - 5.0)) < 1e-12, "sigma = 0 reduces to Poisson");
  bool agree = true;
  for (double n : {0.0, 1.0, 5.0, 40.0, 300.0})
    for (double mu : {0.5, 5.0, 50.0, 250.0})
      for (double sigma : {0.1, 2.0, 20.0})
        agree = agree && std::fabs(profiled_loglike(n, mu, sigma) - brute_profiled_loglike(n, mu, sigma)) < 1e-4;
  check(agree, "analytic profiling matches brute force");
  check(std::fabs(delta_loglike(12, 0.0, 12, 3.0, 0.0)) < 1e-12, "delta lnL vanishes for s = 0");
  check(delta_loglike(10, 30.0, 10, 2.0, 1.0) < -10, "large signal on top of b = n_obs is strongly excluded");

  // 2. MC count interval
  const auto zero = mc_count_interval(0, 3);
  check(zero.first == 0 && zero.second == 9, "zero counts -> [0, z^2]");

  // 3. Behaviour on toy analyses
  std::mt19937_64 rng(12345);
  const std::vector<ToySR> toy = {{2e-3, 12, 10, 2}, {5e-4, 3, 4, 1}, {1e-2, 95, 100, 8}, {1e-4, 0, 0.5, 0.2}};

  const Bounds excl = toy_bounds(toy, 2e4, 250000, 3, rng);
  check(excl.dlnL_upper < -15, "heavily excluded toy point is flagged after 250k events");

  const Bounds insens = toy_bounds(toy, 0.5, 250000, 3, rng);
  check(insens.dlnL_abs < 0.1, "tiny cross-section toy point is flagged as insensitive");

  const Bounds near = toy_bounds(toy, 300, 250000, 3, rng);
  check(near.dlnL_upper > -15 && near.dlnL_abs > 0.1, "borderline toy point is not stopped");

  // 4. Coverage: the upper bound should lie above the true value in (almost) all toys
  for (double xsec_lumi : {50.0, 300.0, 2000.0, 2e4})
  {
    const double truth = toy_true_dlnL(toy, xsec_lumi);
    int n_cover = 0;
    const int n_toys = 2000;
    for (int t = 0; t < n_toys; ++t)
      if (toy_bounds(toy, xsec_lumi, 250000, 3, rng).dlnL_upper >= truth - 1e-9) ++n_cover;
    char msg[160];
    std::snprintf(msg, sizeof msg, "coverage of upper bound for xsec*lumi = %g (true dlnL = %.2f): %.2f%%",
                  xsec_lumi, truth, 100.0 * n_cover / n_toys);
    check(n_cover >= 0.99 * n_toys, msg);
  }

  std::printf("%s\n", n_failed ? "SOME TESTS FAILED" : "All tests passed");
  return n_failed ? 1 : 0;
}
