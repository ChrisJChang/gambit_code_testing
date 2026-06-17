//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  "Core" subset of the shared types: every type
///  shared between more than one backend, model or
///  module, EXCEPT the (heavy, auto-generated) full
///  set of backend types in backend_types_rollcall.hpp.
///
///  This header was split out of shared_types.hpp so
///  that translation units which only need to register
///  models (see model_macros.hpp) can pull in the
///  lightweight model-relevant types without dragging
///  in the complete set of BOSSed backend types (e.g.
///  HepLike, Pythia, ...).
///
///  The full shared_types.hpp simply includes this
///  header and then adds backend_types_rollcall.hpp,
///  so existing includers see no change in behaviour.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author The GAMBIT Collaboration
///  \date 2026 Jun
///
///  *********************************************

#ifndef __shared_types_core_hpp__
#define __shared_types_core_hpp__


#include "gambit/Utils/util_types.hpp"                         // General utility types useful to have around
#include "gambit/Utils/model_parameters.hpp"                   // Definitions required to understand model parameter objects
#include "gambit/Utils/numerical_constants.hpp"                // Centralised constants header

#include "gambit/Elements/sminputs.hpp"                                    // Struct carrying SMINPUTS block (SLHA2)
#include "gambit/Elements/spectrum.hpp"                                    // Carries BSM plus Standard Model spectrum info
#include "gambit/Elements/decay_table.hpp"                                 // Decay table class (carries particle decay info)
#include "gambit/Elements/higgs_couplings_table.hpp"                       // Higgs couplings table class (carries couplings info for entire Higgs sector)
#include "gambit/Elements/slhaea_spec_helpers.hpp"                         // Contains SLHAea reader/writer class alias
#include "gambit/Elements/halo_types.hpp"                                  // data types for DM halo properties
#include "gambit/Elements/wimp_types.hpp"                                  // Containers for generic WIMP dark matter and annihilation properties
#include "gambit/Elements/flav_prediction.hpp"                             // Containers for flavour physics predictions

#include "gambit/Models/SpectrumContents/subspectrum_contents.hpp"         // Contains SpectrumParameter class (names and tags)

#include "gambit/Backends/default_bossed_versions.hpp"         // Default versions of backends to use when employing BOSSed types
#ifdef HAVE_MATHEMATICA
  #include "gambit/Backends/mathematica_variable.hpp"            // Wrapper type for Mathematica global variables
#endif
#include "gambit/Backends/python_variable.hpp"                 // Wrapper type for Python global variables

// Other types that don't belong in any of the existing includes.  As the number of such types grows, they
// should be progressively organised into new headers, and those headers included from here.
namespace Gambit
{
  /// Pointer to a function that takes an integer by reference and returns a double.
  /// Just used for example purposes in ExampleBit_A and ExampleBit_B.
  typedef double(*fptr)(int&);

  /// A double in, double out function pointer
  typedef double(*fptr_dd)(double&);
}


#endif //__shared_types_core_hpp__
