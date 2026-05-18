//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  Macros for creating Python backend functions
///  and variables.
///
///  *********************************************
///
///  Authos (add name and date if you modify):
///
///  \author Pat Scott
///          (p.scott@imperial.ac.uk)
///  \date 2017 Dec
///
///  *********************************************

#ifndef __python_macros_hpp__
#define __python_macros_hpp__

#include "gambit/cmake/cmake_variables.hpp"
#include "gambit/Utils/util_macros.hpp"
#include "gambit/Backends/python_function.hpp"
#include "gambit/Backends/python_variable.hpp"
#include "gambit/Backends/backend_initialiser.hpp"

/// Backend function macro for Python backends
#define BE_FUNCTION_I_PY(NAME, TYPE, ARGLIST, SYMBOLNAME, CAPABILITY, MODELS)                 \
namespace Gambit                                                                              \
{                                                                                             \
  namespace Backends                                                                          \
  {                                                                                           \
    namespace CAT_3(BACKENDNAME,_,SAFE_VERSION)                                               \
    {                                                                                         \
      /* Pointer to python_function object; constructed by initialise_all(). */               \
      python_function<TYPE INSERT_NONEMPTY(STRIP_VARIADIC_ARG(ARGLIST)) >*                    \
       NAME##_function_ptr = nullptr;                                                         \
                                                                                              \
      /* Deferred: construct the python_function object. */                                   \
      namespace                                                                                \
      {                                                                                       \
        int CAT(__pyfun_init_,NAME) =                                                         \
         ::Gambit::Backends::register_backend_initialiser([](){                               \
           NAME##_function_ptr =                                                              \
            new python_function<TYPE INSERT_NONEMPTY(STRIP_VARIADIC_ARG(ARGLIST)) >(          \
             STRINGIFY(BACKENDNAME), STRINGIFY(VERSION), SYMBOLNAME);                         \
         });                                                                                   \
      }                                                                                       \
                                                                                              \
      /* Define a regular function wrapper to call the python_function object. */             \
      TYPE NAME##_function_wrapper FUNCTION_ARGS(ARGLIST)                                     \
      {                                                                                       \
        return (*NAME##_function_ptr) FUNCTION_ARG_NAMES(ARGLIST);                            \
      }                                                                                       \
                                                                                              \
      /* Define a type NAME_type to be a suitable function pointer. */                        \
      typedef TYPE (*NAME##_type) CONVERT_VARIADIC_ARG(ARGLIST);                              \
                                                                                              \
      /* Function pointer set to wrapper; valid as soon as NAME##_function_ptr is set. */     \
      NAME##_type NAME = NAME##_function_wrapper;                                             \
    }                                                                                         \
  }                                                                                           \
}

/// Backend variable macro for Python
#define BE_VARIABLE_I_PY(NAME, TYPE, SYMBOLNAME, CAPABILITY, MODELS)                          \
namespace Gambit                                                                              \
{                                                                                             \
  namespace Backends                                                                          \
  {                                                                                           \
    namespace CAT_3(BACKENDNAME,_,SAFE_VERSION)                                               \
    {                                                                                         \
      /* Pointer to python_variable object; constructed by initialise_all(). */               \
      python_variable<TYPE>* NAME = nullptr;                                                  \
      python_variable<TYPE>* CAT(getptr,NAME)() { return NAME; }                              \
                                                                                              \
      /* Deferred: construct the python_variable object. */                                   \
      namespace                                                                                \
      {                                                                                       \
        int CAT(__pyvar_init_,NAME) =                                                         \
         ::Gambit::Backends::register_backend_initialiser([](){                               \
           NAME = new python_variable<TYPE>(                                                   \
            STRINGIFY(BACKENDNAME), STRINGIFY(VERSION), SYMBOLNAME);                          \
         });                                                                                   \
      }                                                                                       \
    }                                                                                         \
  }                                                                                           \
}

#endif // #defined __python_macros_hpp
