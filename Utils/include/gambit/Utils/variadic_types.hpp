//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  Lightweight variadic template-metaprogramming
///  traits extracted from variadic_functions.hpp.
///
///  Only depends on <type_traits> — suitable for
///  inclusion in low-level headers such as
///  util_types.hpp without pulling in the full STL
///  container set.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author Gregory Martinez
///          (gregory.david.martinez@gmail.com)
///  \date Feb 2014
//
///  \author Christoph Weniger
///          <c.weniger@uva.nl>
///  \date Dec 2014
///
///  *********************************************

#ifndef VARIADIC_TYPES_HPP
#define VARIADIC_TYPES_HPP

#include <type_traits>
#include <string>

namespace Gambit
{
        /////////////////////
        //div_ints_by_half
        /////////////////////

        template <int low, int hi>
        struct div_ints_by_half
        {
                static const int value = (low + hi) >> 1;
        };

        /////////////////////
        //remove_all
        /////////////////////

        template <typename T>
        struct remove_all
        {
                typedef typename std::remove_cv
                <
                        typename std::remove_volatile
                        <
                                typename std::remove_const
                                <
                                        typename std::remove_reference
                                        <
                                                T
                                        >::type
                                >::type
                        >::type
                >::type type;
        };

        //////////////////////////////////////
        //string functions
        //////////////////////////////////////

        inline const std::string stringifyVariadic() {return "";}

        inline const std::string stringifyVariadic(const std::string &str) {return str;}

        template<typename... args>
        inline const std::string stringifyVariadic(const std::string &str, const args&... strs) {return str + ", " + stringifyVariadic(strs...);}

        ///////////////////////////////
        //mult_types
        ///////////////////////////////

        template <typename... args>
        struct mult_types
        {
                typedef void type (args...);
        };

        ////////////////////////////
        //is_same_type
        ////////////////////////////

        template <typename T, typename type>
        struct is_same_type_internal;

        template <typename type>
        struct is_same_type_internal <void (), type>
        {
               static const bool value = false;
        };

        template <typename T, typename... args>
        struct is_same_type_internal <void (T, args...), T>
        {
                static const bool value = true;
        };

        template <typename type, typename T, typename... args>
        struct is_same_type_internal <void (T, args...), type>
        {
                static const bool value = is_same_type_internal <void (args...), type>::value;
        };

        template <typename type, typename T>
        struct is_same_type
        {
                static const bool value = false;
        };

        template <typename T>
        struct is_same_type <T, T>
        {
                static const bool value = true;
        };

        template <typename T, typename... args>
        struct is_same_type <mult_types<args...>, T>
        {
                static const bool value = is_same_type_internal <typename mult_types<args...>::type, T>::value;
        };

        ///////////////////////////
        //is_one_member
        ///////////////////////////

        template <typename type, typename T>
        struct is_one_member_internal;

        template <typename type>
        struct is_one_member_internal <type, void ()>
        {
                static const bool value = false;
        };

        template <typename type, typename T, typename... args>
        struct is_one_member_internal <type, void (T, args...)>
        {
                static const bool value = is_same_type<type, T>::value || is_one_member_internal<type, void (args...)>::value;
        };

        template <typename type, typename... args>
        struct is_one_member
        {
                static const bool value = is_one_member_internal<type, void (args...)>::value;
        };

        //////////////////////////////
        //is_all_member
        //////////////////////////////

        template <typename type, typename T>
        struct is_all_member_internal;

        template <typename type>
        struct is_all_member_internal <type, void ()>
        {
                static const bool value = true;
        };

        template <typename type, typename T, typename... args>
        struct is_all_member_internal <type, void (T, args...)>
        {
                static const bool value = is_same_type<type, T>::value && is_all_member_internal<type, void (args...)>::value;
        };

        template <typename type, typename... args>
        struct is_all_member
        {
                static const bool value = is_all_member_internal<type, void (args...)>::value;
        };

        /////////////////////////////
        //enable_if's
        /////////////////////////////

        template <typename T, typename ret, typename... args>
        struct enable_if_one_member
        {
                typedef std::enable_if<is_one_member<T, args...>::value, ret> type;
        };

        template <typename T, typename ret, typename... args>
        struct enable_if_all_member
        {
                typedef std::enable_if<is_all_member<T, args...>::value, ret> type;
        };

        //////////////////////////////////////
        //enable_if_not's
        //////////////////////////////////////

        template <typename T, typename ret, typename... args>
        struct enable_if_not_one_member
        {
                typedef std::enable_if<!is_one_member<T, args...>::value, ret> type;
        };

        template <typename T, typename ret, typename... args>
        struct enable_if_not_all_member
        {
                typedef std::enable_if<!is_all_member<T, args...>::value, ret> type;
        };

}

#endif
