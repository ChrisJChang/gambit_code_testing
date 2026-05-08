//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  General small utility functions.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author Pat Scott
///          (patscott@physics.mcgill.ca)
///  \date 2013 Apr, July, Aug, Dec
///  \date 2014 Mar
///  \date 2015 Apr
///  \date 2023 Jan
///
///  \author Ben Farmer
///          (benjamin.farmer@monash.edu.au)
///  \date 2013 May, June, July
///
///  *********************************************


#ifndef __util_functions_hpp__
#define __util_functions_hpp__

#include <cmath>

#include "gambit/Utils/util_functions_fwd.hpp"
#include "gambit/cmake/cmake_variables.hpp"

#include <boost/algorithm/string/split.hpp>
#include <boost/algorithm/string/classification.hpp>

extern "C"
{
  #include "mkpath/mkpath.h"
}

namespace Gambit
{

  /// Redirection function to turn an lvalue into an rvalue, so that it
  /// is correctly passed by value when doing perfect forwarding with
  /// functor typecasting.
  template <typename T>
  T byVal(T t) { return t; }

  /// Get the sign of a (hopefully numeric) type
  template <typename T>
  int sgn(T val) { return (T(0) < val) - (val < T(0)); }

  /// Make sure there are no nasty surprises from regular C abs()
  using std::abs;

  /// Convert the memory address a pointer points to to an unsigned integer
  /// (The size of uintptr_t  depends on system & ensures it is big
  /// enough to store memory addresses of the underlying setup)
  template<typename T>
  uintptr_t memaddress_to_uint(T* ptr)
  {
    return reinterpret_cast<uintptr_t>(ptr);
  }

  namespace Utils
  {
    /// Sub-check for are_similar.
    /// true if s1 can be obtained by deleting one character from s2
    bool check1(const str& s1, const str& s2);

    /// Sub-check for are_similar.
    /// true if s1 can be obtained from s2 by changing no more than X characters (X=2 for now)
    bool check2(const str& s1, const str& s2);

    /// Local GAMBIT definition of isnan.  Could be redefined at a later point, depending on compiler support.
    using std::isnan;

    /// Local GAMBIT definition of isinf.  Could be redefined at a later point, depending on compiler support.
    using std::isinf;

    /// Get pointers to beginning and end of array.
    // Useful for initialising vectors with arrays, e.g.
    //   int vv[] = { 12,43 };
    //   std::vector<int> v(beginA(vv), endA(vv));
    // Though 'begin' is unnecessary, can just do
    //   std::vector<int> v(vv, endA(vv));
    template <typename T, size_t N>
    T* beginA(T(&arr)[N]) { return &arr[0]; }
    template <typename T, size_t N>
    T* endA(T(&arr)[N]) { return &arr[0]+N; }

    /// Test if two sets are disjoint (works on any sorted std container I think)
    // From http://stackoverflow.com/questions/1964150/c-test-if-2-sets-are-disjoint
    template<class Set1, class Set2>
    bool is_disjoint(const Set1 &set1, const Set2 &set2)
    {
      if(set1.empty() || set2.empty()) return true;

      typename Set1::const_iterator
          it1 = set1.begin(),
          it1End = set1.end();
      typename Set2::const_iterator
          it2 = set2.begin(),
          it2End = set2.end();

      if(*it1 > *set2.rbegin() || *it2 > *set1.rbegin()) return true;

      while(it1 != it1End && it2 != it2End)
      {
          if(*it1 == *it2) return false;
          if(*it1 < *it2) { it1++; }
          else { it2++; }
      }

      return true;
    }

    // Dummy functions for variadic variables to avoid compiler warnings
    template<typename... T> void dummy_function() {}
    template<typename T> void dummy_function(T one)
    {
      (void)one;
    }

    template<typename T1, typename... T> void dummy_function(T1 first, T... args)
    {
     (void)first;
     dummy_function(args...);
    }

    /// Expunge entries in a container of std::pairs for which the second (boolean) value of the pair is false.
    /// Useful for allowing evaluation of a removal criterion over the whole container in parallel.
    template<template<class, class> class Container, class T >
    void masked_erase(Container<std::pair<T,bool>, std::allocator<std::pair<T,bool>>>& c)
    {
      auto it = std::remove_if(c.begin(), c.end(), [](const std::pair<T,bool>& e) { return not e.second; });
      c.erase(it, c.end());
    }

  }

}

#endif //defined __util_functions_hpp__
