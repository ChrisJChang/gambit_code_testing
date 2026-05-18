//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  Implementation of the deferred backend
///  initialisation registry.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author The GAMBIT Collaboration
///  \date 2024
///
///  *********************************************

#include "gambit/Backends/backend_initialiser.hpp"
#include <vector>
#include <functional>

namespace Gambit
{
  namespace Backends
  {

    namespace
    {
      /// Function-local static (Meyers singleton) guarantees construction before
      /// any TU's static-init callback calls register_backend_initialiser.
      std::vector<std::function<void()>>& initialisers()
      {
        static std::vector<std::function<void()>> v;
        return v;
      }
    }

    int register_backend_initialiser(std::function<void()> f)
    {
      initialisers().push_back(std::move(f));
      return 0;
    }

    void initialise_all()
    {
      for (auto& f : initialisers()) f();
    }

  }
}
