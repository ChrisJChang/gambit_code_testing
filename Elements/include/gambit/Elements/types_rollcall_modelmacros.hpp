//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  Lightweight ("model-only") counterpart to
///  types_rollcall.hpp.
///
///  The in-core model registration machinery
///  (model_macros.hpp, via module_macros_incore_defs.hpp)
///  needs complete types only for the handful of types
///  that models actually traffic in: ModelParameters,
///  double, Options and the model-specific types. It does
///  NOT instantiate functors/dependencies over module
///  result types or backend (BOSSed) types.
///
///  This header therefore pulls in only:
///    - the "core" shared types (shared_types_core.hpp),
///      which excludes backend_types_rollcall.hpp, and
///    - the model-specific types (model_types_rollcall.hpp).
///
///  Compared to the full types_rollcall.hpp it omits:
///    - module_types_rollcall.hpp  (every module's *_types
///      header, e.g. ColliderBit's Pythia wrappers, FlavBit,
///      DarkBit, ... and HEPUtils), and
///    - backend_types_rollcall.hpp (every BOSSed backend
///      type, e.g. HepLike, Pythia, ...).
///
///  This is safe because module rollcall headers each
///  include the full shared_types.hpp plus their own
///  *_types.hpp directly, so modules never rely on the
///  macro machinery to supply their types. Only the model
///  registration path is trimmed.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author The GAMBIT Collaboration
///  \date 2026 Jun
///
///  *********************************************

#ifndef __types_rollcall_modelmacros_hpp__
#define __types_rollcall_modelmacros_hpp__

#include "gambit/Elements/shared_types_core.hpp"      // Shared types, minus the full backend type set
#include "gambit/Models/model_types_rollcall.hpp"     // Model-specific types

#endif /* defined __types_rollcall_modelmacros_hpp__ */
