"""Display-only color maps shared by processing images and video export."""
from matplotlib import colormaps
from matplotlib.colors import LinearSegmentedColormap

CUSTOM_COLORS = {"magenta": "#ff00ff", "yellow": "#ffff00", "blue": "#0000ff"}


def display_colormap(name="inferno"):
    if name in CUSTOM_COLORS:
        return LinearSegmentedColormap.from_list(name, ["#000000", CUSTOM_COLORS[name]])
    if name in ("inferno", "gray", "gray_r"):
        return colormaps[name]
    raise ValueError("Unknown display color map.")
