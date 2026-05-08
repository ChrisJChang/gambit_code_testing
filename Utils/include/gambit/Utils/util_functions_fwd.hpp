//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  Forward declarations of non-template utility
///  functions from util_functions.hpp.
///
///  Include this instead of util_functions.hpp
///  when you only need to call the EXPORT_SYMBOLS
///  functions as opaque calls (no inline/template
///  function bodies needed).
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author Pat Scott
///          (patscott@physics.mcgill.ca)
///  \date 2013 Apr, July, Aug, Dec
///
///  *********************************************

#ifndef __util_functions_fwd_hpp__
#define __util_functions_fwd_hpp__

#include <chrono>
#include <set>
#include <string>
#include <vector>

#include "gambit/Utils/util_types.hpp"

namespace Gambit
{

  namespace Utils
  {

    std::string getEnvVar(std::string const & key);

    EXPORT_SYMBOLS const std::string& GAMBIT_root_dir();
    EXPORT_SYMBOLS const std::string& buildtime_scratch();
    EXPORT_SYMBOLS const str& runtime_scratch();

    EXPORT_SYMBOLS str p2dot(str s);
    EXPORT_SYMBOLS str construct_runtime_scratch(bool fail_on_mpi_uninitialised=true);

    EXPORT_SYMBOLS std::vector<str> delimiterSplit(str s, str delim);
    EXPORT_SYMBOLS str strip_leading_namespace(str s, str ns);
    EXPORT_SYMBOLS str replace_leading_namespace(str s, str ns, str ns_new);
    EXPORT_SYMBOLS void strip_whitespace_except_after_const(str&);
    EXPORT_SYMBOLS void strip_parentheses(str&);

    EXPORT_SYMBOLS bool sspairset_contains(const str&, const std::set<sspair>&);
    EXPORT_SYMBOLS bool sspairset_contains(const str&, const str&, const std::set<sspair>&);
    EXPORT_SYMBOLS bool sspairset_contains(const sspair&, const std::set<sspair>&);

    EXPORT_SYMBOLS str str_fixed_len(str, int);
    EXPORT_SYMBOLS void strcpy2f(char*, int, str);

    EXPORT_SYMBOLS bool endsWith(const std::string& str, const std::string& suffix);
    EXPORT_SYMBOLS bool startsWith(const std::string& str, const std::string& prefix, bool case_sensitive=true);
    EXPORT_SYMBOLS bool iequals(const std::string& a, const std::string& b, bool case_sensitive=false);

    EXPORT_SYMBOLS std::vector<std::string> split(const std::string& input, const std::string& delimiter);
    EXPORT_SYMBOLS std::string strtolower(const std::string& a);
    EXPORT_SYMBOLS std::string quote_if_contains_commas(str);

    struct EXPORT_SYMBOLS ci_less
    {
      bool operator() (const std::string & s1, const std::string & s2) const;
      struct nocase_compare
      {
        bool operator() (const unsigned char& c1, const unsigned char& c2) const;
      };
    };

    EXPORT_SYMBOLS const str& ensure_path_exists(const str&);
    EXPORT_SYMBOLS bool file_exists(const std::string& filename);
    EXPORT_SYMBOLS std::vector<str> ls_dir(const str& dir);
    EXPORT_SYMBOLS str dir_name(const str& path);
    EXPORT_SYMBOLS str base_name(const str& path);
    EXPORT_SYMBOLS int remove_all_files_in(const str& dirname, bool error_if_absent = true);

    typedef std::chrono::time_point<std::chrono::system_clock> time_point;

    EXPORT_SYMBOLS time_point get_clock_now();
    EXPORT_SYMBOLS str return_time_and_date(const time_point& in);
    EXPORT_SYMBOLS bool are_similar(const str& s1, const str& s2);
    EXPORT_SYMBOLS double sqr(double a);
    EXPORT_SYMBOLS bool isInteger(const std::string&);

  }

}

#endif //defined __util_functions_fwd_hpp__
