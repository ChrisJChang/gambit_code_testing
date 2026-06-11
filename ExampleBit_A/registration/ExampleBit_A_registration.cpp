//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  Link-time registration translation unit for
///  ExampleBit_A.
///
///  This file expands ExampleBit_A's rollcall
///  header in the in-core macro context, exactly
///  as the generated module_rollcall.hpp would do
///  inside the Core, but from within a translation
///  unit owned by the module itself.  All functor
///  definitions and registration calls produced by
///  the in-core macros are therefore compiled into
///  this object file, and the registrations happen
///  during static initialisation, before main().
///
///  This file is only compiled into the main gambit
///  executable, and only when the CMake option
///  LINK_TIME_REGISTRATION is ON (in which case the
///  module harvester omits ExampleBit_A's rollcall
///  header from module_rollcall.hpp).  It must NOT
///  be compiled into the ExampleBit_A object
///  library: standalone executables obtain
///  equivalent functor definitions from their own
///  main translation unit via standalone_module.hpp,
///  and would suffer duplicate-symbol errors.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author The GAMBIT Collaboration
///  \date 2026 Jun
///
///  *********************************************

#ifdef LINK_TIME_REGISTRATION

  #include "gambit/Elements/module_macros_incore.hpp"
  #include "gambit/ExampleBit_A/ExampleBit_A_rollcall.hpp"

#endif
