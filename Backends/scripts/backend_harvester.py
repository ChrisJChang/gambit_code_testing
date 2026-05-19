#!/usr/bin/env python
#
#  GAMBIT: Global and Modular BSM Inference Tool
#  *********************************************
#  \file
#
#  Backend and type harvesting script.
#  Generates:
#    backend_rollcall.hpp
#    backend_types_rollcall.hpp
#    ${MODULE}/include/gambit/${MODULE}/${MODULE}_backend_types_rollcall.hpp
#      (one per module, containing only the backend types that module uses)
#
#  This script identifies all the frontend
#  and type headers, and includes them in the
#  relevant auto-generated header files.
#  It also excludes specific backends from this
#  process if specifically asked to.
#
#*********************************************
#
#  Authors (add name and date if you modify):
#
#  \author Pat Scott
#          (patscott@physics.mcgill.ca)
#  \date 2014 Nov
#
#  \author Ben Farmer
#          (b.farmer@imperial.ac.uk)
#  \date 2018 Oct
#
#*********************************************
import os

toolsfile="./Utils/scripts/harvesting_tools.py"
exec(compile(open(toolsfile, "rb").read(), toolsfile, 'exec')) # Python 2/3 compatible version of 'execfile'


def extract_yaml_for_diagnostic(headers):
    """Parses the list of header files and reorganizes them into a dictionary of backend:versions.

    The output is to be used with the diagnostic system. Should be called twice, once for included, once for excluded headers.
    This implementation works for the backend harvester.

    Args:
        headers (list): List of collected header files from the backend harvester.

    Returns:
        dict: backend name key with a list of versions as value
    """
    # Remove the file extension
    headers_without_file_extension = [header.split(".")[0] for header in headers]
    # Get a list of backend names without version numbers
    backend_names = {"_".join(x for x in header.split("_") if not x[0].isdigit()) for header in headers_without_file_extension}

    backend_yaml = {}
    for backend in sorted(backend_names):
        # Because of some overlapping names, we need to also check that the extracted substring actually starts with the version number
        backend_yaml[backend] = sorted(["_".join(x.split(backend)[1:])[1:].replace("_", ".") for x in headers_without_file_extension if x.startswith(backend) and x.split(backend)[1][1].isdigit()])
    return backend_yaml


def build_type_header_maps(verbose):
    """Build lookup maps from backend name to type header paths.

    Returns:
        (regular_headers, bossed_headers) where:
          regular_headers: dict mapping lower-case-normalised stem -> filename (e.g. "darksusy" -> "DarkSUSY.hpp")
          bossed_headers:  dict mapping BACKENDNAME -> list of "dir/loaded_types.hpp" paths
    """
    backend_types_dir = "./Backends/include/gambit/Backends/backend_types"

    # Regular (flat .hpp) type headers: normalised-stem -> filename
    regular_headers = {}
    if os.path.isdir(backend_types_dir):
        for fname in os.listdir(backend_types_dir):
            fpath = os.path.join(backend_types_dir, fname)
            if os.path.isfile(fpath) and (fname.endswith(".hpp") or fname.endswith(".h")):
                stem = re.sub(r'\.[^.]*$', '', fname)  # strip extension
                key = stem.lower().replace('-', '_')
                regular_headers[key] = fname

    # BOSSed type headers: BACKENDNAME -> list of "dir/loaded_types.hpp"
    bossed_headers = {}
    if os.path.isdir(backend_types_dir):
        for dname in sorted(os.listdir(backend_types_dir)):
            dpath = os.path.join(backend_types_dir, dname)
            if not os.path.isdir(dpath):
                continue
            id_file = os.path.join(dpath, "identification.hpp")
            loaded_file = os.path.join(dpath, "loaded_types.hpp")
            if not (os.path.isfile(id_file) and os.path.isfile(loaded_file)):
                continue
            with open(id_file, 'r', errors='replace') as f:
                for line in f:
                    m = re.match(r'\s*#define\s+BACKENDNAME\s+(\w+)', line)
                    if m:
                        bname = m.group(1)
                        if bname not in bossed_headers:
                            bossed_headers[bname] = []
                        bossed_headers[bname].append(dname + "/loaded_types.hpp")
                        break

    if verbose:
        print("Regular backend type headers: " + str(regular_headers))
        print("BOSSed backend type headers: " + str(bossed_headers))

    return regular_headers, bossed_headers


def lookup_type_headers_for_backend(backend_name, regular_headers, bossed_headers):
    """Given a backend name (from BACKEND_OPTION or NEEDS_CLASSES_FROM), return matching type header paths.

    For regular backends: the header whose normalised stem is a prefix of the normalised backend name.
    For BOSSed backends: all loaded_types.hpp files whose BACKENDNAME matches the backend name exactly.
    """
    result = []
    key = backend_name.lower().replace('-', '_')

    # BOSSed: exact BACKENDNAME match
    if backend_name in bossed_headers:
        result.extend(bossed_headers[backend_name])

    # Regular: stem must be a non-empty prefix of the backend name
    best_stem = ""
    best_fname = None
    for stem_key, fname in regular_headers.items():
        if key.startswith(stem_key) and len(stem_key) > len(best_stem):
            best_stem = stem_key
            best_fname = fname
    if best_fname is not None:
        result.append(best_fname)

    return result


def build_reverse_type_map(regular_headers, verbose):
    """Build a map from struct/class type names (in flat backend type headers) to header filenames.

    Only captures actual struct/class definitions (not forward declarations ending with ';').
    Returns: dict mapping type_name -> header_filename
    """
    backend_types_dir = "./Backends/include/gambit/Backends/backend_types"

    type_to_header = {}
    for fname in sorted(regular_headers.values()):
        fpath = os.path.join(backend_types_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with io.open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            continue
        # Match struct/class definitions that are NOT forward declarations.
        # re.MULTILINE anchors ^ to start of each line.
        # The negative lookahead (?!\s*;) excludes forward declarations like 'class Foo;'.
        for m in re.finditer(
                r'^\s*(?:struct|class)\s+([A-Za-z_][A-Za-z0-9_]*)(?!\s*;)(?!\s*>)',
                content, re.MULTILINE):
            type_name = m.group(1)
            # Skip generic template parameter names ('T', 'U', 'Key', 'Value', etc.)
            if len(type_name) <= 2:
                continue
            if type_name not in type_to_header:
                type_to_header[type_name] = fname

    if verbose:
        print("Reverse type map ({} entries):".format(len(type_to_header)))
        for k, v in sorted(type_to_header.items()):
            print("  {} -> {}".format(k, v))

    return type_to_header


def extract_types_used_in_macros(filepath):
    """Extract type name tokens used in module rollcall macros.

    Handles: DEPENDENCY(cap, TYPE), MODEL_CONDITIONAL_DEPENDENCY(cap, TYPE, ...),
             START_FUNCTION(TYPE), START_FUNCTION(TYPE, FLAG),
             START_CONDITIONAL_DEPENDENCY(TYPE),
             BACKEND_REQ(name, (tags), TYPE, (args)),
             BACKEND_REQ_FROM_GROUP(group, name, (tags), TYPE, (args)),
             QUICK_FUNCTION(MODULE, CAP, FLAG, FUNC, TYPE, ...)

    Returns: set of individual identifier tokens found in type arguments.
    """
    tokens = set()
    try:
        with io.open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = comment_remover(f.read())
    except Exception:
        return tokens

    type_strings = set()

    # DEPENDENCY(capability, TYPE) — second argument
    for m in re.finditer(r'\bDEPENDENCY\s*\(\s*\w+\s*,\s*([^)]+?)\s*\)', content):
        type_strings.add(m.group(1).strip())

    # MODEL_CONDITIONAL_DEPENDENCY(capability, TYPE, models...) — second argument
    for m in re.finditer(r'\bMODEL_CONDITIONAL_DEPENDENCY\s*\(\s*\w+\s*,\s*([^,)]+)', content):
        type_strings.add(m.group(1).strip())

    # START_FUNCTION(TYPE) or START_FUNCTION(TYPE, FLAG) — first argument
    for m in re.finditer(r'\bSTART_FUNCTION\s*\(\s*([^,)]+?)(?:\s*,|\s*\))', content):
        type_strings.add(m.group(1).strip())

    # START_CONDITIONAL_DEPENDENCY(TYPE) — first argument
    for m in re.finditer(r'\bSTART_CONDITIONAL_DEPENDENCY\s*\(\s*([^)]+?)\s*\)', content):
        type_strings.add(m.group(1).strip())

    # BACKEND_REQ(name, (tags), TYPE, (args)) — third argument (after closing ')' of tags)
    for m in re.finditer(r'\bBACKEND_REQ\s*\(\s*\w+\s*,\s*\([^)]*\)\s*,\s*([^,)]+?)(?:\s*,\s*\(|\s*\))', content):
        type_strings.add(m.group(1).strip())

    # BACKEND_REQ_FROM_GROUP(group, name, (tags), TYPE, ...) — fourth argument
    for m in re.finditer(r'\bBACKEND_REQ_FROM_GROUP\s*\(\s*\w+\s*,\s*\w+\s*,\s*\([^)]*\)\s*,\s*([^,)]+?)(?:\s*,|\s*\))', content):
        type_strings.add(m.group(1).strip())

    # QUICK_FUNCTION(MODULE, CAP, FLAG, FUNC, TYPE, ...) — fifth argument
    for m in re.finditer(r'\bQUICK_FUNCTION\s*\(\s*\w+\s*,\s*\w+\s*,\s*\w+\s*,\s*\w+\s*,\s*([^,)]+?)(?:\s*,|\s*\))', content):
        type_strings.add(m.group(1).strip())

    # Tokenize all extracted type strings into individual identifiers
    for type_str in type_strings:
        for token in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', type_str):
            tokens.add(token)

    return tokens


def extract_backend_names_from_file(filepath):
    """Extract all declared backend names from a single header file.

    Parses BACKEND_OPTION, SET_BACKEND_OPTION (which uses (BackendName, version...) tuples),
    NEEDS_CLASSES_FROM, and also detects namespace-qualified types used in module macros
    (e.g. START_FUNCTION(DarkAges::Energy_injection_spectrum) implies a dependency on DarkAges).
    """
    backends = set()
    try:
        with io.open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = comment_remover(f.read())
    except Exception:
        return backends

    # BACKEND_OPTION((BackendName, ...), (tag))
    for m in re.finditer(r'BACKEND_OPTION\s*\(\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)', content):
        backends.add(m.group(1))

    # SET_BACKEND_OPTION(func, (BackendName, version, ...)) — second arg is the version tuple
    for m in re.finditer(r'SET_BACKEND_OPTION\s*\(\s*\w+\s*,\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)', content):
        backends.add(m.group(1))

    # NEEDS_CLASSES_FROM(BackendName, ...) — for BOSSed backends
    for m in re.finditer(r'NEEDS_CLASSES_FROM\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)', content):
        backends.add(m.group(1))

    # Namespace-qualified types in module macros: BackendName::SomeType
    # This catches cases like START_FUNCTION(DarkAges::Energy_injection_spectrum)
    # or BACKEND_REQ(func, (tag), MicrOmegas::aChannel*, ())
    # Filter out well-known non-backend namespaces to avoid false positives.
    non_backend_namespaces = {
        "std", "boost", "Gambit", "pybind11", "Eigen", "HepMC", "HepMC3",
        "Pythia8", "YAML", "ROOT", "LHEF", "LHAPDF", "fastjet"
    }
    for m in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*)::[A-Za-z_]', content):
        ns = m.group(1)
        if ns not in non_backend_namespaces:
            backends.add(ns)

    return backends


def find_backends_for_module(module_name, reverse_type_map, verbose):
    """Scan all headers in a module's include directory for backend declarations.

    Uses both direct backend name detection (BACKEND_OPTION, NEEDS_CLASSES_FROM, namespace
    patterns) and a reverse type map to detect backends needed only via DEPENDENCY macros
    that reference unqualified backend-specific struct/class types.

    Returns the set of all backend names declared in the module.
    """
    module_include_dir = os.path.join(".", module_name, "include", "gambit", module_name)
    if not os.path.isdir(module_include_dir):
        return set()

    backends = set()
    type_headers_needed = set()

    for root, dirs, files in os.walk(module_include_dir):
        for fname in files:
            if fname.endswith(('.hpp', '.h', '.hh')):
                fpath = os.path.join(root, fname)
                # Direct backend name detection via macros and namespace patterns
                new_backends = extract_backend_names_from_file(fpath)
                backends.update(new_backends)
                # Reverse type map: detect unqualified backend types in DEPENDENCY etc.
                tokens = extract_types_used_in_macros(fpath)
                for token in tokens:
                    if token in reverse_type_map:
                        type_headers_needed.add(reverse_type_map[token])

    if verbose and (backends or type_headers_needed):
        print("  Module {}: backends declared = {}, extra type headers = {}".format(
            module_name, sorted(backends), sorted(type_headers_needed)))

    return backends, type_headers_needed


def generate_per_module_backend_type_rollcalls(regular_headers, bossed_headers, reverse_type_map, exclude_backends, verbose):
    """Generate a per-module backend types rollcall header for each module.

    Each generated file includes only the backend type headers that the module
    actually uses (as declared via BACKEND_OPTION, SET_BACKEND_OPTION, or
    NEEDS_CLASSES_FROM in its rollcall and other include headers, or referenced
    as unqualified types in DEPENDENCY/START_FUNCTION macros).

    Generated file location: ${MODULE}/include/gambit/${MODULE}/${MODULE}_backend_types_rollcall.hpp
    """
    # Discover modules by walking the source tree for *_rollcall.hpp files
    exclude_dirs = {"build", ".git", "runs", "scratch", "contrib", "Backends",
                    ".github", "Logs", "pippi", "Models", "yaml_files", "Printers",
                    "config", "doc", "Utils", "Elements", "cmake", "Core", "ScannerBit"}

    modules_found = []
    for root, dirs, files in os.walk(".", topdown=True):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for fname in files:
            prefix = re.sub(r"_rollcall\.h.*$", "", fname)
            if (fname.lower().endswith("_rollcall.hpp") and
                    "bit" in fname.lower() and
                    os.path.basename(root) == prefix):
                module_name = prefix
                if module_name not in modules_found:
                    modules_found.append(module_name)

    if verbose:
        print("\nModules found for per-module backend type generation: " + str(sorted(modules_found)))

    for module_name in sorted(modules_found):
        if excluded(module_name, exclude_backends):
            if verbose:
                print("  Skipping excluded module: " + module_name)
            continue

        # Find all backend names declared in this module's headers,
        # and extra type headers needed via the reverse type map.
        backend_names, type_headers_for_module = find_backends_for_module(module_name, reverse_type_map, verbose)

        # Map backend names to type headers (adds to what reverse map already found)
        for bname in backend_names:
            headers = lookup_type_headers_for_backend(bname, regular_headers, bossed_headers)
            type_headers_for_module.update(headers)

        # Write the generated header
        output_path = os.path.join(".", module_name, "include", "gambit", module_name,
                                   module_name + "_backend_types_rollcall.hpp")
        guard = "__{}_backend_types_rollcall_hpp__".format(module_name)

        towrite = """//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \\file
///
///  Compile-time registration of backend types
///  needed by module {module}.
///
///  This file was automatically generated by
///  backend_harvester.py. Do not modify.
///
///  To add a backend type dependency for {module},
///  declare it via BACKEND_OPTION or
///  NEEDS_CLASSES_FROM in the module rollcall
///  and re-run backend_harvester.py.
///
///  *********************************************
///
///  \\author The GAMBIT Collaboration
///  \\date {date}
///
///  *********************************************

#ifndef {guard}
#define {guard}

#include "gambit/Utils/type_macros.hpp"

""".format(module=module_name,
           date=datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y"),
           guard=guard)

        if type_headers_for_module:
            towrite += "// Backend type definitions required by module {}.\n".format(module_name)
            for h in sorted(type_headers_for_module):
                towrite += '#include "gambit/Backends/backend_types/{}"\n'.format(h)
        else:
            towrite += "// No backend-specific types required by module {}.\n".format(module_name)

        towrite += "\n#endif // defined {}\n".format(guard)

        # Write via temp file and only update if different (avoids spurious recompilation)
        tmp_path = output_path + ".candidate"
        output_dir = os.path.dirname(output_path)
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)
        with open(tmp_path, "w") as f:
            f.write(towrite)
        update_only_if_different(output_path, tmp_path, verbose)

    if verbose:
        print("Generated per-module backend type rollcall headers.\n")


def main(argv):

    frontend_headers=set([])
    frontend_headers_excluded=set([])
    backend_type_headers = set([])
    bossed_backend_type_headers = set([])
    exclude_backends=set([])

    # Handle command line options
    verbose = False
    try:
        opts, args = getopt.getopt(argv,"vx:",["verbose","exclude-backends="])
    except getopt.GetoptError:
        print('Usage: backend_harvestor.py [flags]')
        print(' flags:')
        print('        -v                       : More verbose output')
        print('        -x backend1,backend2,... : Exclude backend1, backend2, etc.')
        sys.exit(2)
    for opt, arg in opts:
      if opt in ('-v','--verbose'):
        verbose = True
        print('backend_harvester.py: verbose=True')
      elif opt in ('-x','--exclude-backends'):
        exclude_backends.update(neatsplit(",",arg))

    # Get list of frontend header files to include in backend_rollcall.hpp
    frontend_headers.update(retrieve_generic_headers(verbose,"./Backends/include/gambit/Backends/frontends","frontend",exclude_backends))
    frontend_headers_excluded.update(retrieve_generic_headers(verbose,"./Backends/include/gambit/Backends/frontends","frontend",exclude_backends, retrieve_excluded=True))
    # Get list of backend type header files
    backend_type_headers.update(retrieve_generic_headers(verbose,"./Backends/include/gambit/Backends/backend_types","backend type",set([])))
    bossed_backend_type_headers.update(retrieve_generic_headers(verbose,"./Backends/include/gambit/Backends/backend_types","BOSSed type",set([])))
    # Remove bossed backends from list of excluded backends
    exclude_backends = set([be for be in exclude_backends if not any([excluded(bossed_be, [be]) for bossed_be in bossed_backend_type_headers])])
    # Get list of frontend header files to include in backend_rollcall.hpp
    frontend_headers.update(retrieve_generic_headers(verbose,"./Backends/include/gambit/Backends/frontends","frontend",exclude_backends))

    if verbose:
        print("Frontend headers identified:")
        for h in frontend_headers:
            print('  gambit/Backends/frontends/'+h)
        print("Backend type headers identified:")
        for h in backend_type_headers:
            print('  gambit/Backends/backend_types/'+h)
        for h in bossed_backend_type_headers:
            print('  gambit/Backends/backend_types/'+h)

    # Generate a c++ header containing all the frontend headers we have just harvested.
    towrite = """//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \\file
///
///  Compile-time registration of available back-
///  ends.
///
///  This file was automatically generated by
///  backend_harvester.py. Do not modify.
///
///  Do not add to this if you want to add a new
///  backend -- just add your frontend header to
///  Backends/include/gambit/Backends/frontends
///  and rest assured that backend_harvester.py
///  will make sure it ends up here.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \\author The GAMBIT Collaboration
///  \\date """+datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y")+"""
///
///  *********************************************

#ifndef __backend_rollcall_hpp__
#define __backend_rollcall_hpp__

// Include the backend macro definitions
#include \"gambit/Backends/backend_macros.hpp\"

// Automatically-generated list of frontends.
"""

    for h in frontend_headers:
        towrite+='#include \"gambit/Backends/frontends/{0}\"\n'.format(h)
    towrite+="\n#endif // defined __backend_rollcall_hpp__\n"

    with open("./Backends/include/gambit/Backends/backend_rollcall.hpp","w") as f:
        f.write(towrite)

    # Generate a c++ header containing all the frontend headers we have just harvested.
    towrite = """//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \\file
///
///  Compile-time registration of backend types.
///
///  This file was automatically generated by
///  backend_harvester.py. Do not modify.
///
///  Do not add to this if you want to add new
///  types associated with a new (or old) backend.
///  Just add your backend type headers to the
///  directory tree in the right place, and rest
///  assured that backend_harvester.py will make
///  sure they end up here.
///
///  Where is \'the right place\'?
///  -Regular backend types: in a new header file
///    Backends/include/gambit/Backends/backend_types/X_types.hpp
///   where X is the name of the backend.
///  -When the types you want to add are a result
///   of running BOSS: add the directory created
///   by BOSS as
///    Backends/include/gambit/Backends/backend_types/X/
///   where X is the name of the backend.  BOSS
///   will actually do this itself automatically
///   in some circumstances.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \\author The GAMBIT Collaboration
///  \\date """+datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y")+"""
///
///  *********************************************

#ifndef __backend_types_rollcall_hpp__
#define __backend_types_rollcall_hpp__

// Macro definitions
#include \"gambit/Utils/type_macros.hpp\"

// Regular backend type definitions.
"""
    for h in backend_type_headers:
        towrite+='#include \"gambit/Backends/backend_types/{0}\"\n'.format(h)

    towrite += "\n// BOSSed backend type definitions.\n"
    for h in bossed_backend_type_headers:
        towrite+='#include \"gambit/Backends/backend_types/{0}\"\n'.format(h)

    towrite+="\n#endif // defined __backend_types_rollcall_hpp__\n"

    with open("./Backends/include/gambit/Backends/backend_types_rollcall.hpp","w") as f:
        f.write(towrite)

    if verbose:
        print("Generated backend_rollcall.hpp.")
        print("Generated backend_types_rollcall.hpp.\n")

    import yaml
    with open("./config/gambit_backends.yaml", "w+") as f:
        yaml.dump({
            "enabled": extract_yaml_for_diagnostic(frontend_headers),
            "disabled": extract_yaml_for_diagnostic(frontend_headers_excluded)
        }, f)

    # Generate per-module backend type rollcall headers
    regular_headers, bossed_headers = build_type_header_maps(verbose)
    reverse_type_map = build_reverse_type_map(regular_headers, verbose)
    generate_per_module_backend_type_rollcalls(regular_headers, bossed_headers, reverse_type_map, exclude_backends, verbose)

# Handle command line arguments (verbosity)
if __name__ == "__main__":
   main(sys.argv[1:])
