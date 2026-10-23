//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  ColliderBit Monte Carlo convergence routines.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author Pat Scott
///          (p.scott@imperial.ac.uk)
///  \date 2018 Jan
///  \date 2019 Jan
///
///  \author Anders Kvellestad
///          (anders.kvellestad@fys.uio.no)
///  \date 2018 May
///
///  \author Chris Chang
///  \date 2026 Oct
///
///  *********************************************

#include <omp.h>
#include <algorithm>
#include "gambit/ColliderBit/MC_convergence.hpp"
#include "gambit/ColliderBit/analyses/AnalysisContainer.hpp"
#include "gambit/ColliderBit/analyses/Analysis.hpp"
#include "gambit/Utils/standalone_error_handlers.hpp"

// #define COLLIDERBIT_DEBUG

namespace Gambit
{
  namespace ColliderBit
  {

    /// A map containing pointers to all instances of this class
    std::map<const MC_convergence_checker* const, bool> MC_convergence_checker::convergence_map;

    /// A map containing the latest adaptive-stopping bounds from all instances of this class
    std::map<const MC_convergence_checker* const, std::pair<int,AdaptiveStopping::Bounds>> MC_convergence_checker::adaptive_map;

    /// Constructor
    MC_convergence_checker::MC_convergence_checker() : n_threads(omp_get_max_threads()), converged(false)
    {
      n_signals = new std::vector<int>[n_threads];
      convergence_map[this] = false;
    }

    /// Deconstructor
    MC_convergence_checker::~MC_convergence_checker()
    {
      delete[] n_signals;
    }

    /// Initialise (or re-initialise) the object
    void MC_convergence_checker::init(const convergence_settings& settings)
    {
      clear();
      set_settings(settings);
    }

    /// Provide a pointer to the convergence settings
    void MC_convergence_checker::set_settings(const convergence_settings& settings)
    {
      if (omp_get_thread_num() > 0) utils_error().raise(LOCAL_INFO, "Cannot call this function from inside an OpenMP block.");
      _settings = &settings;
    }

    /// Clear all convergence data (for all threads)
    void MC_convergence_checker::clear()
    {
      if (omp_get_thread_num() > 0) utils_error().raise(LOCAL_INFO, "Cannot call this function from inside an OpenMP block.");
      converged = false;
      convergence_map[this] = false;
      adaptive_map.erase(this);
      for (int i = 0; i != n_threads; ++i)
      {
        n_signals[i].clear();
      }
    }


    /// Update the convergence data.  This is the only routine meant to be called in parallel.
    void MC_convergence_checker::update(const AnalysisContainer& ac)
    {
      // Abort if the analysis container tracked by this object is already fully converged
      // (unless adaptive stopping still needs up-to-date counts)
      if (converged and not _settings->adaptive_stopping) return;

      // Work out the thread number.
      int my_thread = omp_get_thread_num();

      // Loop over all the analyses and populate their current signal predictions
      n_signals[my_thread].clear();
      for (auto& analysis_pointer_pair : ac.get_current_analyses_map())
      {
        // Loop over all the signal regions in this analysis
        for (auto& sr : analysis_pointer_pair.second->get_results())
        {
          // Update the number of accepted events in this signal region
          n_signals[my_thread].push_back(sr.n_sig_MC);
        }
      }
    }


    /// Check if convergence has been achieved across threads, and across all instances of this class
    bool MC_convergence_checker::achieved(const AnalysisContainer& ac)
    {
      if (not converged)
      {

        int SR_index = -1;
        // Loop over all analyses
        bool analysis_converged;
        bool all_analyses_converged = true; // Will be set to false if any analysis is not converged
        for (auto& analysis_pointer_pair : ac.get_current_analyses_map())
        {

          analysis_converged = false;

          // Loop over all the signal regions in this analysis
          bool SR_converged;
          bool all_SR_converged = true;  // Will be set to false if any SR is not converged
          for (auto& sr : analysis_pointer_pair.second->get_results())
          {
            SR_converged = false;
            SR_index += 1;

            // Sum signal count across threads
            const int SR_counts = total_counts(SR_index);

            double fractional_stat_uncert = (SR_counts == 0 ? 1.0 : 1.0/sqrt(SR_counts));
            double absolute_stat_uncert = SR_counts * fractional_stat_uncert;
            SR_converged = (_settings->stop_at_sys and SR_counts > 0 and absolute_stat_uncert <= sr.n_sig_MC_sys) or
                   (fractional_stat_uncert <= _settings->target_stat);

            if (not SR_converged) all_SR_converged = false;

            #ifdef COLLIDERBIT_DEBUG
              cerr << endl;
              cerr << "DEBUG: SIGNAL REGION " << SR_index << " of " << n_signals[0].size() << endl;
              cerr << "DEBUG: SR label: " << sr.sr_label << " in analysis " << analysis_pointer_pair.first << endl;
              cerr << "DEBUG: absolute_stat_uncert vs sys: " << absolute_stat_uncert << " vs " << sr.n_sig_MC_sys << endl;
              cerr << "DEBUG: fractional_stat_uncert vs target: " << fractional_stat_uncert << " vs " << _settings->target_stat << endl;
              cerr << "DEBUG: Is this SR done? " << SR_converged << endl;
            #endif

            if (SR_converged)
            {
              // Shortcut
              if (not _settings->all_analyses_must_converge and not _settings->all_SR_must_converge)
              {
                converged = true;
                convergence_map[this] = true;
                return true;
              }

              if (not _settings->all_SR_must_converge)
              {
                analysis_converged = true;
                break; // break signal region loop
              }
            }
            else  // SR not converged
            {
              // Shortcut
              if (_settings->all_analyses_must_converge and _settings->all_SR_must_converge)
              {
                return false;
              }
            }
          } // End loop over SRs

          if (_settings->all_SR_must_converge) analysis_converged = all_SR_converged;

          #ifdef COLLIDERBIT_DEBUG
            cerr << endl;
            cerr << "DEBUG: Done looping over SRs for analysis " << analysis_pointer_pair.first << endl;
            cerr << "DEBUG: analysis_converged =  " << analysis_converged << endl;
          #endif

          if (not analysis_converged) all_analyses_converged = false;

          // Shortcut
          if (analysis_converged and not _settings->all_analyses_must_converge)
          {
            converged = true;
            convergence_map[this] = true;
            return true;
          }
          else if (not analysis_converged and _settings->all_analyses_must_converge)
          {
            return false;
          }

        } // End loop over analyses

        #ifdef COLLIDERBIT_DEBUG
          cerr << endl;
          cerr << "DEBUG: Done looping over analyses in this container" << endl;
          cerr << "DEBUG: Current variable values:" << endl;
          cerr << "DEBUG: analysis_converged = " << analysis_converged << endl;
          cerr << "DEBUG: all-analysis_converged = " << all_analyses_converged << endl;
        #endif

        if (not all_analyses_converged) return false;
        converged = true;
        convergence_map[this] = true;
      } // end: if (not converged

      // Now check if all instances of this class have also set their entry in the convergence map to true,
      // implying that all analyses in all containers have reached convergence.
      if (_settings->all_analyses_must_converge)
      {
        for (auto& it : convergence_map)
        {
          if (not it.second) return false;
        }
        return true;
      }
      return true;
    }


    /// Total signal MC count in a given SR, summed over threads
    int MC_convergence_checker::total_counts(int SR_index) const
    {
      int total = 0;
      for (int j = 0; j != n_threads; j++) total += n_signals[j][SR_index];
      return total;
    }


    /// Evaluate the likelihood-aware adaptive stopping criterion at an event-loop checkpoint
    bool MC_convergence_checker::adaptive_stop(const AnalysisContainer& ac, int n_events, int n_containers, adaptive_stopping_record& record)
    {
      // Without a valid cross-section the MC counts cannot be turned into expected events
      if (n_events <= 0 or _settings->xsec_fb < 0) return false;

      // Bounds for the analyses in this container, summed as in LHC_Combined_LogLike
      AdaptiveStopping::Bounds container_bounds;
      const std::vector<str>& ignored = _settings->adaptive_ignore_analyses;
      int SR_index = -1;
      for (auto& analysis_pointer_pair : ac.get_current_analyses_map())
      {
        Analysis* analysis = analysis_pointer_pair.second;
        // The special "Baselines" analysis is never part of the loglike (cf. calc_LHC_LogLikes_common)
        const bool ignore = analysis_pointer_pair.first == "Baselines" or
                            std::find(ignored.begin(), ignored.end(), analysis_pointer_pair.first) != ignored.end();
        const double scale = _settings->xsec_fb * analysis->luminosity() / n_events;

        std::vector<AdaptiveStopping::SRCounts> srs;
        for (auto& sr : analysis->get_results())
        {
          SR_index += 1;
          if (ignore) continue;
          srs.push_back({sr.n_obs, sr.n_bkg, sr.n_bkg_err, double(total_counts(SR_index)), sr.n_sig_MC_sys, scale});
        }
        if (ignore) continue;

        const AdaptiveStopping::Bounds analysis_bounds = AdaptiveStopping::analysis_bounds(srs, _settings->adaptive_n_sigma_MC);
        container_bounds.dlnL_upper += analysis_bounds.dlnL_upper;
        container_bounds.dlnL_abs += analysis_bounds.dlnL_abs;

        #ifdef COLLIDERBIT_DEBUG
          cerr << "DEBUG: adaptive stopping: " << analysis_pointer_pair.first << " after " << n_events << " events: "
               << "dlnL_upper = " << analysis_bounds.dlnL_upper << ", dlnL_abs = " << analysis_bounds.dlnL_abs << endl;
        #endif
      }
      adaptive_map[this] = {n_events, container_bounds};

      // Wait until every analysis container has reported for this checkpoint
      AdaptiveStopping::Bounds total;
      int n_reported = 0;
      for (auto& it : adaptive_map)
      {
        if (it.second.first != n_events) continue;
        total.dlnL_upper += it.second.second.dlnL_upper;
        total.dlnL_abs += it.second.second.dlnL_abs;
        n_reported++;
      }
      if (n_reported < n_containers) return false;

      record.n_checkpoints++;
      record.latest = total;

      int reason = ADAPTIVE_NO_STOP;
      if (total.dlnL_upper < -_settings->adaptive_dlnL_threshold) reason = ADAPTIVE_EXCLUDED;
      else if (total.dlnL_abs < _settings->adaptive_insensitive_dlnL) reason = ADAPTIVE_INSENSITIVE;
      if (reason == ADAPTIVE_NO_STOP) return false;

      if (record.n_events_at_stop < 0)
      {
        record.n_events_at_stop = n_events;
        record.stop_reason = reason;
        record.at_stop = total;
      }
      return not _settings->adaptive_log_only;
    }

  }
}
