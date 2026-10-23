//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  Functions of ColliderBit event loop.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author Abram Krislock
///          (a.m.b.krislock@fys.uio.no)
///
///  \author Aldo Saavedra
///
///  \author Andy Buckley
///
///  \author Chris Rogan
///          (crogan@cern.ch)
///  \date 2014 Aug
///  \date 2015 May
///
///  \author Pat Scott
///          (p.scott@imperial.ac.uk)
///  \date 2015 Jul
///  \date 2018 Jan
///  \date 2019 Jan
///
///  \author Anders Kvellestad
///          (anders.kvellestad@fys.uio.no)
///  \date   2017 March
///  \date   2018 Jan
///  \date   2018 May
///
///  \author Tomas Gonzalo
///          (tomas.gonzalo@kit.edu)
///  \date 2023 Aug
///
///  \author Chris Chang
///  \date 2026 Oct
///
///  *********************************************

#include "gambit/Elements/gambit_module_headers.hpp"
#include "gambit/ColliderBit/ColliderBit_eventloop.hpp"
#include "gambit/ColliderBit/PoissonCalculators.hpp"
#include "gambit/ColliderBit/analyses/Analysis.hpp"

// #define COLLIDERBIT_DEBUG
#define DEBUG_PREFIX "DEBUG: OMP thread " << omp_get_thread_num() << ":  " << __FILE__ << ":" << __LINE__ << ":  "

namespace Gambit
{

  namespace ColliderBit
  {

    /// Calculate the required number of MC events
    /// Currently can pick between fixed, or provide the mean and pull from a Poisson
    int calc_N_MC(std::string method, double n_mc_mean)
    {
      if (method == "UMVUE")
      {
        return Gambit::ColliderBit::PoissonCalculators::umvue_draw_n_mc_threadsafe(n_mc_mean);
      }
      else
      {
        // default to fixed
        return n_mc_mean;
      }
    }


    /// Get the maximum luminosity required for any analysis in a given collider
    double GetMaxLumi(const std::vector<str>& analyses)
    {
      AnalysisContainer Container;

      try
      {
        Container.init(analyses);
      }
      catch (std::runtime_error& e)
      {
        ColliderBit_error().raise(LOCAL_INFO,"Failed to initialise Analysis Containers in GetMaxLumi.");
      }

      // Loop over all analyses and get the maximum luminosity
      double max_lumi = 0.0;
      if (Container.has_analyses())
      {
        for (auto& analysis_pointer_pair : Container.get_current_analyses_map())
        {
          double lumi = analysis_pointer_pair.second->luminosity();
          if (lumi > max_lumi) {max_lumi = lumi;}
        }
      }

      return max_lumi;
    }


    /// LHC Loop Manager
    void operateLHCLoop(MCLoopInfo& result)
    {
      using namespace Pipes::operateLHCLoop;
      static std::streambuf *coutbuf = std::cout.rdbuf(); // save cout buffer for running the loop quietly

      #ifdef COLLIDERBIT_DEBUG
        cout << DEBUG_PREFIX << endl;
        cout << DEBUG_PREFIX << "~~~~ New point! ~~~~" << endl;
      #endif

      // Retrieve run options from the YAML file (or standalone code)
      static bool first = true;
      static bool silenceLoop;
      static std::map<str,int> min_nEvents;
      static std::map<str,int> max_nEvents;
      static std::map<str,int> stoppingres;
      static std::map<str,int> adaptive_first_check;
      static std::map<str,double> adaptive_growth;
      static bool fixed_nEvents = true;
      if (first)
      {
        // Should we silence stdout during the loop?
        silenceLoop = runOptions->getValueOrDef<bool>(true, "silenceLoop");

        // Retrieve all collider names form the YAML options
        result.collider_names = runOptions->getValueOrDef<std::vector<str>>(std::vector<str>(), "use_colliders");
        if ((result.collider_names).size() == 0)
        {
          ColliderBit_error().set_fatal(true); // This one must regarded fatal since there is something wrong in the user input
          ColliderBit_error().raise(LOCAL_INFO,"Cannot find any collider names in use_colliders option for operateLHCLoop. Please correct your YAML file.");
        }


        // Retrieve the options for each collider.
        for (auto& collider : result.collider_names)
        {
          Options colOptions(runOptions->getValue<YAML::Node>(collider));

          result.analyses[collider]                                       = colOptions.getValueOrDef<std::vector<str>>(std::vector<str>(), "analyses");
          // Check that the analyses all correspond to actual ColliderBit analyses, and sort them into separate maps for each detector.
          for (str& analysis : result.analyses.at(collider))
          {
            result.detector_analyses[collider][getDetector(analysis)].push_back(analysis);
          }

          // Specify whether the number of MC events should be the same for each param point
          fixed_nEvents = colOptions.hasKey("max_nEvents");

          // Check that the nEvents options given make sense.
          if (  (colOptions.hasKey("mean_nEvents") and colOptions.hasKey("mean_relative_nEvents"))
             or (colOptions.hasKey("mean_nEvents") and colOptions.hasKey("max_nEvents"))
             or (colOptions.hasKey("max_nEvents")  and colOptions.hasKey("mean_relative_nEvents")))
          {
            ColliderBit_error().set_fatal(true); // This one must regarded fatal since there is something wrong in the user input
            ColliderBit_error().raise(LOCAL_INFO,"Options mean_nEvents, mean_relative_nEvents and max_nEvents must not be used together for collider"
                                                 +collider+". Please correct your YAML file.");
          }

          min_nEvents[collider]                                           = colOptions.getValueOrDef<int>(10000, "min_nEvents");
          max_nEvents[collider]                                           = colOptions.getValueOrDef<int>(10000, "max_nEvents");
          double mean_nEvents                                             = colOptions.getValueOrDef<double>(10000, "mean_nEvents");
          result.ratio_MC_expected[collider]                              = colOptions.getValueOrDef<double>(1.0, "mean_relative_nEvents");
          result.estimator                                                = colOptions.getValueOrDef<std::string>("MLE", "poisson_like_estimator");

          // Check that the nEvents options given make sense.
          if (fixed_nEvents and (min_nEvents.at(collider) > max_nEvents.at(collider)) )
          {
            ColliderBit_error().set_fatal(true); // This one must regarded fatal since there is something wrong in the user input
            ColliderBit_error().raise(LOCAL_INFO,"Option min_nEvents is greater than corresponding max_nEvents for collider "
                                                 +collider+". Please correct your YAML file.");
          }

          // In the case of a relative number of events, set mean_nEvents based on expected nEvents
          if (colOptions.hasKey("mean_relative_nEvents"))
          {
            double max_lumi = GetMaxLumi(result.analyses.at(collider));

            std::map<std::string, xsec_container> xsec_map = *Dep::InitialTotalCrossSection;
            double xsec = xsec_map[collider].xsec();
            mean_nEvents = max_lumi * xsec * result.ratio_MC_expected[collider];

            #ifdef COLLIDERBIT_DEBUG
              // Check for zero events
              if (mean_nEvents == 0)
              {
                cout << DEBUG_PREFIX << "Zero events predicted for collider " + collider + ". Perhaps consider a cross-section veto." << endl;
              }
            #endif
          }

          result.mean_nEvents                                             = mean_nEvents;
          result.desired_nEvents[collider]                                = calc_N_MC(result.estimator, mean_nEvents);
          result.convergence_options[collider].target_stat                = colOptions.getValue<double>("target_fractional_uncert");
          result.convergence_options[collider].stop_at_sys                = colOptions.getValueOrDef<bool>(true, "halt_when_systematic_dominated");
          result.convergence_options[collider].all_analyses_must_converge = colOptions.getValueOrDef<bool>(false, "all_analyses_must_converge");
          result.convergence_options[collider].all_SR_must_converge       = colOptions.getValueOrDef<bool>(false, "all_SR_must_converge");
          result.maxFailedEvents[collider]                                = colOptions.getValueOrDef<int>(1, "maxFailedEvents");
          result.invalidate_failed_points[collider]                       = colOptions.getValueOrDef<bool>(false, "invalidate_failed_points");
          stoppingres[collider]                                           = colOptions.getValueOrDef<int>(200, "events_between_convergence_checks");

          // Options for likelihood-aware adaptive stopping (frequentist scans only)
          convergence_settings& conv = result.convergence_options[collider];
          conv.adaptive_stopping         = colOptions.getValueOrDef<bool>(false, "adaptive_stopping");
          conv.adaptive_log_only         = colOptions.getValueOrDef<bool>(false, "adaptive_log_only");
          conv.adaptive_dlnL_threshold   = colOptions.getValueOrDef<double>(conv.adaptive_dlnL_threshold, "adaptive_delta_lnL_threshold");
          conv.adaptive_n_sigma_MC       = colOptions.getValueOrDef<double>(conv.adaptive_n_sigma_MC, "adaptive_n_sigma_MC");
          conv.adaptive_insensitive_dlnL = colOptions.getValueOrDef<double>(conv.adaptive_insensitive_dlnL, "adaptive_insensitive_delta_lnL");
          conv.adaptive_ignore_analyses  = colOptions.getValueOrDef<std::vector<str>>(std::vector<str>(), "adaptive_ignore_analyses");
          adaptive_first_check[collider] = colOptions.getValueOrDef<int>(250000, "adaptive_first_check");
          adaptive_growth[collider]      = colOptions.getValueOrDef<double>(2.0, "adaptive_growth");

          if (conv.adaptive_stopping and (not fixed_nEvents or result.estimator == "UMVUE"))
          {
            ColliderBit_error().set_fatal(true); // This one must regarded fatal since there is something wrong in the user input
            ColliderBit_error().raise(LOCAL_INFO,"Option adaptive_stopping requires max_nEvents and cannot be used with the UMVUE estimator for collider "
                                                 +collider+". Please correct your YAML file.");
          }
          if (conv.adaptive_stopping and (adaptive_first_check.at(collider) <= 0 or adaptive_growth.at(collider) <= 1.0))
          {
            ColliderBit_error().set_fatal(true); // This one must regarded fatal since there is something wrong in the user input
            ColliderBit_error().raise(LOCAL_INFO,"Options adaptive_first_check must be > 0 and adaptive_growth > 1 for collider "
                                                 +collider+". Please correct your YAML file.");
          }
          result.event_count[collider]                                    = 0;

          // In the case of using the UMVUE estimator, override some options
          if (result.estimator == "UMVUE")
          {
            if (fixed_nEvents)
            {
              ColliderBit_error().set_fatal(true); // This one must regarded fatal since there is something wrong in the user input
              ColliderBit_error().raise(LOCAL_INFO,"Options min_nEvents and max_nEvents should not be used for the UMVUE estimator for collider "
                                                   +collider+". Please correct your YAML file.");
            }

            // Avoid convergence checks by setting the number of events higher than are actually generated
            stoppingres[collider] = result.desired_nEvents[collider]*2;
          }
        }
        first = false;
      }

      // Do the base-level initialisation
      Loop::executeIteration(BASE_INIT);

      // Mute stdout during the loop if requested
      if (silenceLoop) std::cout.rdbuf(0);

      // For every collider requested in the yaml file:
      for (auto& collider : result.collider_names)
      {

        // Reset the event_generation_began and exceeded_maxFailedEvents flags
        result.reset_flags();

        // Update the collider
        result.set_current_collider(collider);

        // Initialise the count of the number of generated events.
        result.current_event_count() = 0;

        // Reset the adaptive-stopping record and pass on the cross-section for this point
        result.adaptive_records[collider] = adaptive_stopping_record();
        auto xsec_it = Dep::InitialTotalCrossSection->find(collider);
        result.current_convergence_options().xsec_fb = (xsec_it == Dep::InitialTotalCrossSection->end() ? -1. : xsec_it->second.xsec());

        #ifdef COLLIDERBIT_DEBUG
          cout << DEBUG_PREFIX << "operateLHCLoop: Current collider is " << collider << "." << endl;
        #endif

        piped_invalid_point.check();
        Loop::reset();

        // Do the single-thread part of the collider initialization
        #ifdef COLLIDERBIT_DEBUG
          cout << DEBUG_PREFIX << "operateLHCLoop: Will execute COLLIDER_INIT" << endl;
        #endif
        Loop::executeIteration(COLLIDER_INIT);
        // Any problem during COLLIDER_INIT step?
        piped_warnings.check(ColliderBit_warning());
        piped_errors.check(ColliderBit_error());
        piped_invalid_point.check();

        // Do the OMP parallelized part of the collider initialization
        #ifdef COLLIDERBIT_DEBUG
          cout << DEBUG_PREFIX << "operateLHCLoop: Will execute COLLIDER_INIT_OMP" << endl;
        #endif
        #pragma omp parallel
        {
          Loop::executeIteration(COLLIDER_INIT_OMP);
        }
        // Any problems during the COLLIDER_INIT_OMP step?
        piped_warnings.check(ColliderBit_warning());
        piped_errors.check(ColliderBit_error());
        piped_invalid_point.check();

        // Execute the sigle-thread iteration XSEC_CALCULATION
        #ifdef COLLIDERBIT_DEBUG
          cout << DEBUG_PREFIX << "operateLHCLoop: Will execute XSEC_CALCULATION" << endl;
        #endif
        Loop::executeIteration(XSEC_CALCULATION);
        // Any problems during the XSEC_CALCULATION step?
        piped_warnings.check(ColliderBit_warning());
        piped_errors.check(ColliderBit_error());
        piped_invalid_point.check();

        //
        // The main OMP parallelized sections begin here
        //
        #ifdef COLLIDERBIT_DEBUG
          cout << DEBUG_PREFIX << "operateLHCLoop: Will execute START_SUBPROCESS" << endl;
        #endif
        result.current_event_count() = 0;
        #pragma omp parallel
        {
          Loop::executeIteration(START_SUBPROCESS);
        }
        // Any problems during the START_SUBPROCESS step?
        piped_warnings.check(ColliderBit_warning());
        piped_errors.check(ColliderBit_error());
        piped_invalid_point.check();

        const int max_nEvents_collider = max_nEvents.at(collider);
        const int min_nEvents_collider = min_nEvents.at(collider);
        const int stoppingres_collider = stoppingres.at(collider);
        const int desired_nEvents_collider = result.desired_nEvents[collider];

        // Adaptive-stopping checkpoints: adaptive_first_check * adaptive_growth^k, below max_nEvents
        const bool adaptive = result.current_convergence_options().adaptive_stopping;
        int next_adaptive_check = adaptive_first_check.at(collider);
        bool adaptive_pending = adaptive and next_adaptive_check < max_nEvents_collider;

        // Convergence loop
        while(((fixed_nEvents && result.current_event_count() < max_nEvents_collider) or (!fixed_nEvents && result.current_event_count() < desired_nEvents_collider)) and not *Loop::done)
        {

          int eventCountBetweenConvergenceChecks = 0;
          const int eventsBeforeNextCheck = adaptive_pending ? std::min(stoppingres_collider, next_adaptive_check - result.current_event_count())
                                                             : stoppingres_collider;
          #ifdef COLLIDERBIT_DEBUG
            cout << DEBUG_PREFIX << "Starting main event loop.  Will do " << eventsBeforeNextCheck << " events before testing convergence." << endl;
          #endif

          // Main event loop
          result.event_generation_began = true;
          #pragma omp parallel
          {
            while(eventCountBetweenConvergenceChecks < eventsBeforeNextCheck and
                  ((fixed_nEvents && result.current_event_count() < max_nEvents_collider) or (!fixed_nEvents && result.current_event_count() < desired_nEvents_collider)) and
                  not *Loop::done and
                  not result.end_of_event_file and
                  not result.exceeded_maxFailedEvents and
                  not piped_errors.inquire()
                  )
            {
              bool thread_do_iteration = true;
              int thread_my_iteration;

              // Increment counters before executing the corresponding event loop iteration,
              // to stop other threads from starting any event iterations beyond max_nEvents.
              #pragma omp critical
              {
                if (   (fixed_nEvents && result.current_event_count() < max_nEvents_collider)
                    or (!fixed_nEvents && result.current_event_count() < desired_nEvents_collider))
                {
                  result.current_event_count()++;
                  thread_my_iteration = result.current_event_count();
                  eventCountBetweenConvergenceChecks++;
                }
                else
                {
                  thread_do_iteration = false;
                }
              }

              if(thread_do_iteration)
              {
                try
                {
                  // Execute event loop iteration
                  Loop::executeIteration(thread_my_iteration);
                }
                catch (std::domain_error& e)
                {
                  cout << "\n   Caught std::domain_error. Continuing to the next event...\n\n";
                  // Decrement counters since the event iteration failed
                  #pragma omp critical
                  {
                    result.current_event_count()--;
                    eventCountBetweenConvergenceChecks--;
                  }
                }
              }

            } // end while loop

          } // end omp parallel block

          // Any problems during the main event loop?
          piped_warnings.check(ColliderBit_warning());
          piped_errors.check(ColliderBit_error());
          piped_invalid_point.check();

          #ifdef COLLIDERBIT_DEBUG
            cout << DEBUG_PREFIX << "Did " << eventCountBetweenConvergenceChecks << " events of " << result.current_event_count() << " simulated so far." << endl;
          #endif

          // Break convergence loop if too many events fail
          if(result.exceeded_maxFailedEvents) break;

          // Don't bother with precision-based convergence if we haven't passed the minimum number of events yet.
          // Only do this if we are using a fixed number of events.
          result.precision_check = fixed_nEvents and result.current_event_count() >= min_nEvents_collider;
          result.adaptive_checkpoint = adaptive_pending and result.current_event_count() >= next_adaptive_check;
          if (result.adaptive_checkpoint)
          {
            next_adaptive_check = std::max(next_adaptive_check + 1, int(std::ceil(next_adaptive_check * adaptive_growth.at(collider))));
            adaptive_pending = next_adaptive_check < max_nEvents_collider;
          }
          if (result.precision_check or result.adaptive_checkpoint)
          {
            #pragma omp parallel
            {
              Loop::executeIteration(COLLECT_CONVERGENCE_DATA);
            }
            // Any problems during the COLLECT_CONVERGENCE_DATA step?
            piped_warnings.check(ColliderBit_warning());
            piped_errors.check(ColliderBit_error());

            Loop::executeIteration(CHECK_CONVERGENCE);
            // Any problems during the CHECK_CONVERGENCE step?
            piped_warnings.check(ColliderBit_warning());
            piped_errors.check(ColliderBit_error());
          }

        }

        #ifdef COLLIDERBIT_DEBUG
          cerr << DEBUG_PREFIX << "Final event count: current_event_count() = " << result.current_event_count() << endl;
        #endif

        #pragma omp parallel
        {
          Loop::executeIteration(END_SUBPROCESS);
        }
        // Any problems during the END_SUBPROCESS step?
        piped_warnings.check(ColliderBit_warning());
        piped_errors.check(ColliderBit_error());
        piped_invalid_point.check();

        //
        // OMP parallelized sections end here
        //

        Loop::executeIteration(COLLIDER_FINALIZE);

        // Any problems during the COLLIDER_FINALIZE step?
        piped_warnings.check(ColliderBit_warning());
        piped_errors.check(ColliderBit_error());
        piped_invalid_point.check();
      }

      // Nicely thank the loop for being quiet, and restore everyone's vocal chords
      if (silenceLoop) std::cout.rdbuf(coutbuf);

      Loop::executeIteration(BASE_FINALIZE);

      // Any problems during the BASE_FINALIZE step?
      piped_warnings.check(ColliderBit_warning());
      piped_errors.check(ColliderBit_error());
      piped_invalid_point.check();

    }


    /// Store some information about the event generation
    void getLHCEventLoopInfo(map_str_dbl& result)
    {
      using namespace Pipes::getLHCEventLoopInfo;
      result.clear();
      result["did_event_generation"] = double(Dep::RunMC->event_generation_began);
      result["too_many_failed_events"] = double(Dep::RunMC->exceeded_maxFailedEvents);
      for (auto& name : Dep::RunMC->collider_names)
      {
        result["event_count_" + name] = Dep::RunMC->event_count.at(name);

        // Adaptive-stopping diagnostics
        if (Dep::RunMC->convergence_options.at(name).adaptive_stopping)
        {
          auto rec_it = Dep::RunMC->adaptive_records.find(name);
          const adaptive_stopping_record rec = (rec_it == Dep::RunMC->adaptive_records.end() ? adaptive_stopping_record() : rec_it->second);
          result["adaptive_n_checkpoints_" + name] = rec.n_checkpoints;
          result["adaptive_stop_reason_" + name] = rec.stop_reason;
          result["adaptive_events_at_stop_" + name] = rec.n_events_at_stop;
          result["adaptive_dlnL_upper_at_stop_" + name] = rec.at_stop.dlnL_upper;
          result["adaptive_dlnL_abs_at_stop_" + name] = rec.at_stop.dlnL_abs;
          result["adaptive_dlnL_upper_latest_" + name] = rec.latest.dlnL_upper;
          result["adaptive_dlnL_abs_latest_" + name] = rec.latest.dlnL_abs;
        }
      }
    }


    /// Loop over all analyses and collect them in one place
    void CollectAnalyses(AnalysisDataPointers& result)
    {
      using namespace Pipes::CollectAnalyses;
      static bool first = true;
      static bool print_cutflows;
      static bool normalized_cutflows;

      // Start with an empty vector
      result.clear();

      #ifdef COLLIDERBIT_DEBUG
        cout << DEBUG_PREFIX << "CollectAnalyses: Dep::ATLASAnalysisNumbers->size()    = " << Dep::ATLASAnalysisNumbers->size() << endl;
        cout << DEBUG_PREFIX << "CollectAnalyses: Dep::CMSAnalysisNumbers->size()      = " << Dep::CMSAnalysisNumbers->size() << endl;
        cout << DEBUG_PREFIX << "CollectAnalyses: Dep::IdentityAnalysisNumbers->size() = " << Dep::IdentityAnalysisNumbers->size() << endl;
      #endif

      // Add results
      if (Dep::ATLASAnalysisNumbers->size() != 0) result.insert(result.end(), Dep::ATLASAnalysisNumbers->begin(), Dep::ATLASAnalysisNumbers->end());
      if (Dep::CMSAnalysisNumbers->size() != 0) result.insert(result.end(), Dep::CMSAnalysisNumbers->begin(), Dep::CMSAnalysisNumbers->end());
      if (Dep::IdentityAnalysisNumbers->size() != 0) result.insert(result.end(), Dep::IdentityAnalysisNumbers->begin(), Dep::IdentityAnalysisNumbers->end());

      // When first called, check that all analyses contain at least one signal region.
      if (first)
      {
        // Print cutflow at the end of the run
        print_cutflows = runOptions->getValueOrDef<bool>(false, "print_cutflows");
        normalized_cutflows = runOptions->getValueOrDef<bool>(false, "normalized_cutflows");

        // Loop over all AnalysisData pointers
        for (auto& adp : result)
        {
          if (adp->size() == 0)
          {
            str errmsg;
            errmsg = "The analysis " + adp->analysis_name + " has no signal regions.";
            ColliderBit_error().raise(LOCAL_INFO, errmsg);
          }
        }
        first = false;
      }

      // Print cutflows of analyses
      if(print_cutflows)
      {
        std::cout << "Cutflows" << std::endl;
        std::cout << "========" << std::endl;
        for(auto& adp : result)
        {
          std::cout << adp->analysis_name << std::endl;
          std::cout << "-----------------" << std::endl;

          if(normalized_cutflows)
          {
            adp->cutflows.normalize(Dep::TotalCrossSection->xsec() * adp->luminosity);
          }
          std::cout << adp->cutflows << std::endl;
        }
      }

      // #ifdef COLLIDERBIT_DEBUG
      //   cout << DEBUG_PREFIX << "CollectAnalyses: Current size of 'result': " << result.size() << endl;
      //   if (result.size() > 0)
      //   {
      //     cout << DEBUG_PREFIX << "CollectAnalyses: Will loop through 'result'..." << endl;
      //     for (auto& adp : result)
      //     {
      //       cout << DEBUG_PREFIX << "CollectAnalyses: 'result' contains AnalysisData pointer to " << adp << endl;
      //       cout << DEBUG_PREFIX << "CollectAnalyses: -- Will now loop over all signal regions in " << adp << endl;
      //       for (auto& sr : adp->srdata)
      //       {
      //         cout << DEBUG_PREFIX << "CollectAnalyses: -- " << adp << " contains signal region: " << sr.sr_label << ", n_sig_MC = " << sr.n_sig_MC << ", n_sig_scaled = " << n_sig_scaled << endl;
      //       }
      //       cout << DEBUG_PREFIX << "CollectAnalyses: -- Done looping over signal regions in " << adp << endl;
      //     }
      //     cout << DEBUG_PREFIX << "CollectAnalyses: ...Done looping through 'result'." << endl;
      //   }
      // #endif
    }


  }

}
