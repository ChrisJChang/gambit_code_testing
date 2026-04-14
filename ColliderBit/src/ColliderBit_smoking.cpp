//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  ColliderBit module functions for the smoking backend.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author Christopher Chang
///          (c.j.chang@fys.uio.no)
///  \date 2026 Apr
///
///  *********************************************

#include "gambit/Elements/gambit_module_headers.hpp"
#include "gambit/ColliderBit/ColliderBit_rollcall.hpp"
#include "gambit/Backends/backend_types/smoking.hpp"

#include "gambit/Utils/slhaea_helpers.hpp"

namespace Gambit
{
  namespace ColliderBit
  {

    /// Run the smoking NLO+NLL cross-section calculation with default settings.
    void runSmoking(double &result)
    {
      using namespace Pipes::runSmoking;

      smoking_variables vars;
      // TODO: This should be done in the frontend, not here...
      // const str backendDir = Backends::backendInfo().path_dir(STRINGIFY(smoking), STRINGIFY(VERSION));
      // TODO: If done properly in frontend header, can use bandendDir to automatically get this.
      //       I am just gonna try it hacked for now.
      vars.slha_file = "/home/chris-chang/WORK/GAMBIT/CB_development/SMOKING_backend/gambit/Backends/installed/smoking/1.0.0/example/sps1a.slha";

      // std::ifstream slhafilein(vars.slha_file);
      // const SLHAea::Coll* slhaea = new SLHAea::Coll(slhafilein);
      SLHAstruct slhaea = read_SLHA(vars.slha_file);
      vars.slhaea = slhaea;

      std::cout << "HEY CHRIS. I got here after reading in the SLHA..." << std::endl;
      
      BEreq::smoking_init(vars);
      BEreq::smoking_calc(vars);
      BEreq::smoking_finalise();

      result = 0.0;
    }

  }
}
