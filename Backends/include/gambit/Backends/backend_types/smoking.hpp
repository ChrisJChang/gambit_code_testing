//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///  \file
///
///  GAMBIT-side type definitions for the smoking backend.
///
///  These structs mirror the definitions in smoking's
///  include/smoking/settings.h and include/smoking/input_parser.h.
///  Both sides must remain in sync so that the binary layout matches
///  when a smoking_variables reference is passed across the dlopen
///  boundary into init_SMOKING / Calculate_cross_section.
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author Christopher Chang
///          (christopher.chang@uqconnect.edu.au)
///  \date 2026 Apr
///
///  *********************************************

#ifndef __smoking_types_hpp__
#define __smoking_types_hpp__

#include <string>
#include <vector>

// ---------------------------------------------------------------------------
// Types from smoking's include/smoking/settings.h
// ---------------------------------------------------------------------------

struct IntegratorConfig
{
  std::string backend  = "GSL";
  std::string strategy = "VEGAS";
  bool   use_GPU_integrator = false;
  int    chunksize          = 8192;
  double err_tol_rel        = 5e-2;
  size_t max_iters          = 10;
  size_t n_call             = 0;
};

struct VegasParams   { double alpha = 1.5; };
struct SuaveParams   {};
struct DivonneParams {};
struct CuhreParams   {};

// ---------------------------------------------------------------------------
// Types from smoking's include/smoking/input_parser.h
// ---------------------------------------------------------------------------

struct smoking_variables
{
  double sqrt_s = 13600.0;
  int    ipid1  = 2212;
  int    ipid2  = 2212;
  std::vector<int> pid1;
  std::vector<int> pid2;

  int  order = 1;
  bool dm    = false;
  bool dt    = false;
  std::vector<std::string> diff_name;
  std::vector<double>      diff_val;
  int default_scheme = 0;

  int scale_scheme = 0;
  std::vector<double> central_scale;
  double central_scale_F, central_scale_R;
  std::vector<double> scale_ratio;
  double scale_ratio_F, scale_ratio_R;
  bool scale_error    = false;
  int  scale_strategy = 3;

  bool        alphas_error = false;
  bool        pdf_error    = false;
  std::string pdf_set      = "PDF4LHC15_nnlo_100";
  bool        model_alphas;     // intentionally uninitialised, matching smoking
  std::string slha_file    = "example/sps1a.slha";
  SLHAea::Coll slhaea;
  bool        output       = false;
  std::string output_file;

  bool diffname_flag       = false;
  bool diffval_flag        = false;
  bool scale_flag          = false;
  bool central_scale_flag  = false;
  bool scale_ratio_flag    = false;
  bool output_file_name    = false;

  double xmin                    = 0;
  bool   PDFxmin                 = false;
  bool   invMellin_force_physical = false;

  double NLP    = 1;
  double NLL    = 1;
  double NNLL   = 0;
  double H_1loop = 0;
  double H_2loop = 0;

  IntegratorConfig int_config;
  VegasParams      vegas_params;
  SuaveParams      suave_params;
  DivonneParams    divonne_params;
  CuhreParams      cuhre_params;
};

#endif /* defined __smoking_types_hpp__ */
