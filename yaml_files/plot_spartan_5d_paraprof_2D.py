"""Plot the 2D profile likelihoods for the spartan_5d.yaml paraprof run,
using gambit_plotting_tools and the GAMBIT hdf5 output.

Generates one plot per paraprof projection in spartan_5d.yaml:
  (x1, x2) and (x2, x3).

Bin counts and axis bounds are matched to the paraprof YAML settings
(200 x 200 native grid over [-3, 3] x [-3, 3]) to avoid re-binning
artefacts.

Install gambit_plotting_tools first:
    pip install --user git+https://github.com/GambitBSM/gambit_plotting_tools.git
(on Debian/Ubuntu you may need SETUPTOOLS_USE_DISTUTILS=stdlib).

Run from the repository root:
    python3 yaml_files/plot_spartan_5d_paraprof_2D.py
"""

from copy import deepcopy
import numpy as np
import matplotlib.pyplot as plt

import gambit_plotting_tools.gambit_plot_utils as plot_utils
import gambit_plotting_tools.gambit_plot_settings as gambit_plot_settings
from gambit_plotting_tools.annotate import add_header


HDF5_FILE = "runs/spartan_5d/samples/results.hdf5"
GROUP_NAME = "data"

# Match paraprof's native (grid_points) and Parameters bounds in spartan_5d.yaml
XY_BINS  = (200, 200)
PAR_RANGE = [-3.0, 3.0]

# Keys for each parameter we plot
PARAMS = ["x1", "x2", "x3"]
datasets = [("LogLike", ("LogLike", float))]
for p in PARAMS:
    datasets.append(
        (p, (f"#trivial_5d_parameters @trivial_5d::primary_parameters::{p}", float))
    )

data = plot_utils.read_hdf5_datasets([(HDF5_FILE, GROUP_NAME)], datasets,
                                     filter_invalid_points=True)
print(f"Read {len(data['LogLike'])} valid points; "
      f"LogLike range = [{np.min(data['LogLike']):.3f}, "
      f"{np.max(data['LogLike']):.3f}]")


confidence_levels = [0.954, 0.683]
contour_values = plot_utils.get_2D_likelihood_ratio_levels(confidence_levels)

plot_labels = {
    "x1":      r"$x_1$",
    "x2":      r"$x_2$",
    "x3":      r"$x_3$",
    "LogLike": r"$\ln L$",
}

base_settings = deepcopy(gambit_plot_settings.plot_settings)
base_settings["interpolation"] = True
base_settings["interpolation_resolution"] = 400
base_settings["contour_colors"]     = ["white", "white"]
base_settings["contour_linestyles"] = ["solid", "dashed"]
base_settings["contour_linewidths"] = [1.0, 1.0]


def make_plot(x_key, y_key):
    z_key = "LogLike"
    labels = (plot_labels[x_key], plot_labels[y_key], plot_labels[z_key])
    xy_bounds = (PAR_RANGE, PAR_RANGE)

    fig, ax, _ = plot_utils.plot_2D_profile(
        data[x_key], data[y_key], data[z_key],
        labels, XY_BINS,
        xy_bounds=xy_bounds,
        z_bounds=None,
        z_is_loglike=True,
        plot_likelihood_ratio=True,
        contour_levels=contour_values,
        add_max_likelihood_marker=True,
        missing_value_color=base_settings["colormap"](0.0),
        plot_settings=base_settings,
    )

    header_text = r"Rosenbrock 5D, paraprof scanner"
    if plt.rcParams.get("text.usetex"):
        header_text = header_text.replace("paraprof scanner",
                                          r"\textsf{paraprof} scanner")
    add_header(header_text, ax=ax)

    out = f"runs/spartan_5d/plots/2D_profile_{x_key}_{y_key}.png"
    plot_utils.create_folders_if_not_exist(out)
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"Wrote file: {out}")


for x_key, y_key in [("x1", "x2"), ("x2", "x3")]:
    make_plot(x_key, y_key)
