//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  Registry for deferred backend initialisation.
///  Each backend frontend TU registers a callable
///  here during static init; initialise_all() runs
///  them all in insertion order from main().
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author The GAMBIT Collaboration
///  \date 2024
///
///  *********************************************

#ifndef __BACKEND_INITIALISER_HPP__
#define __BACKEND_INITIALISER_HPP__

#include <functional>

namespace Gambit
{
  namespace Backends
  {

    /// Register a callable to be invoked by initialise_all().
    /// Returns 0 so it can be used in a global int-initialiser.
    int register_backend_initialiser(std::function<void()> f);

    /// Run all registered backend initialisers in insertion order.
    /// Must be called from a single thread before any backend symbols are used.
    void initialise_all();

  }
}

#endif // __BACKEND_INITIALISER_HPP__
