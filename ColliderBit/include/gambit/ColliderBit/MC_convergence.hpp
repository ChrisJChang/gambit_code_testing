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

#ifndef __MC_convergence_hpp__
#define __MC_convergence_hpp__

#include "gambit/Utils/util_types.hpp"
#include "gambit/ColliderBit/MC_adaptive_stopping.hpp"

namespace Gambit
{
  namespace ColliderBit
  {

    /// Forward declaration
    class AnalysisContainer;

    /// Type for holding Monte Carlo convergence settings
    struct convergence_settings
    {
      double target_stat;
      bool stop_at_sys;
      bool all_analyses_must_converge;
      bool all_SR_must_converge;

      /// Likelihood-aware adaptive stopping (frequentist scans only)
      bool adaptive_stopping = false;
      /// Evaluate and record the adaptive stopping decision, but never stop
      bool adaptive_log_only = false;
      /// Stop if the optimistic LHC delta lnL (s+b vs b) is below -threshold
      double adaptive_dlnL_threshold = 15.;
      /// Number of sigmas used for the MC-count interval of each SR
      double adaptive_n_sigma_MC = 3.;
      /// Stop if the bound on |delta lnL| summed over all SRs is below this
      double adaptive_insensitive_dlnL = 0.1;
      /// Analyses left out of the stopping decision (e.g. those skipped in LHC_Combined_LogLike)
      std::vector<str> adaptive_ignore_analyses;
      /// Total cross-section (fb) for the current point, used to scale MC counts mid-loop
      double xsec_fb = -1.;
    };

    /// Reasons for stopping the event loop early
    enum adaptive_stop_reason { ADAPTIVE_NO_STOP = 0, ADAPTIVE_EXCLUDED = 1, ADAPTIVE_INSENSITIVE = 2 };

    /// Record of the adaptive stopping decisions for one parameter point and collider
    struct adaptive_stopping_record
    {
      /// Number of checkpoints at which all analysis containers were evaluated
      int n_checkpoints = 0;
      /// Event count at which the stopping criterion was first met (-1: never)
      int n_events_at_stop = -1;
      /// Reason for stopping (an adaptive_stop_reason)
      int stop_reason = ADAPTIVE_NO_STOP;
      /// Bounds from the latest checkpoint
      AdaptiveStopping::Bounds latest;
      /// Bounds at the checkpoint where the criterion was first met
      AdaptiveStopping::Bounds at_stop;
    };

    /// Helper class for testing for convergence of analyses
    class MC_convergence_checker
    {
      private:

        /// A pointer to the convergence settings to use
        const convergence_settings* _settings;

        /// Pointer to an array holding the signal counts on each thread
        std::vector<int>* n_signals;

        /// Total number of threads that the checker is configured to deal with
        int n_threads;

        /// Flag indicating if everything tracked by this instance is converged
        bool converged;

        /// A map containing pointers to all instances of this class
        static std::map<const MC_convergence_checker* const, bool> convergence_map;

        /// Latest adaptive-stopping bounds from each instance, with the event count they were computed at
        static std::map<const MC_convergence_checker* const, std::pair<int,AdaptiveStopping::Bounds>> adaptive_map;

        /// Total signal MC count in a given SR, summed over threads
        int total_counts(int SR_index) const;

      public:

        /// Constructor
        MC_convergence_checker();

        /// Destructor
        ~MC_convergence_checker();

        /// Initialise (or re-initialise) the object
        void init(const convergence_settings&);

        /// Provide a pointer to the convergence settings
        void set_settings(const convergence_settings&);

        /// Clear all convergence data (for all threads)
        void clear();

        /// Update the convergence data.  This is the only routine meant to be called in parallel.
        void update(const AnalysisContainer&);

        /// Check if convergence has been achieved across threads, and across all instances of this class
        bool achieved(const AnalysisContainer& ac);

        /// Evaluate the likelihood-aware adaptive stopping criterion at an event-loop checkpoint.
        /// The decision is only taken once all n_containers analysis containers have reported for
        /// this event count; it is written to record. Returns true if the event loop should stop.
        bool adaptive_stop(const AnalysisContainer& ac, int n_events, int n_containers, adaptive_stopping_record& record);
    };


  }
}

#endif