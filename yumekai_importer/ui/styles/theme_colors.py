"""Dark equivalents for the existing light theme's visual colours.

Light styles remain the source of truth; the dark theme only substitutes colours.
Brand yellow and its dark text retain their original contrast.
"""

import re

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


_DARK_COLORS = {}


def _colors(dark, *light):
    _DARK_COLORS.update({value: dark for value in light})


_colors("#211C25", "#FFFFFF")
_colors("#28222D", "#F7F5F8", "#F7F7F7", "#F8F6FB", "#FAF8FB", "#FCFAFC")
_colors("#19151E", "#FCF7FC", "#FFFEF6")
_colors("#2E2633", "#F3F0F4", "#F4F2F4", "#F4F2F5", "#F6F4F7", "#F0E8F1", "#ECE7ED")
_colors("#2A232F", "#F3EDF4")
_colors("#F4EBF5", "#201A22", "#24212C", "#302432", "#312735", "#352837")
_colors("#E8D1E8", "#45304E", "#503B5B", "#513C4E", "#544258", "#60416B")
_colors("#C5B7CB", "#695D6E", "#645866", "#74657C", "#756B77", "#796D7B", "#725D7A")
_colors("#BEAAC2", "#80697E", "#8C728E", "#8C7A94", "#978B98")
_colors("#968A9F", "#807584", "#9B8DA2", "#9B91A0", "#A59BA6")
_colors("#584058", "#ECD7E8", "#EAD7EA")
_colors("#3D2F46", "#F1EAF5", "#F2E5F0", "#F3EEF6", "#F3EDF6", "#F5EFF7", "#F7EFF7", "#FAF1F8")
_colors("#493651", "#E7DBEE", "#E8DEEF", "#E9DDED")
_colors("#58415F", "#DAC9E3")
_colors("#584B61", "#CDC5D0", "#CFC5D2")
_colors("#46394E", "#DED9E0", "#DED1E5", "#DCCFDE", "#E1D9E7", "#E2D7E7", "#E5DFE8", "#E7DEE7", "#E8E2EC")
_colors("#B99AB9", "#896B84", "#A1849D", "#A68CAD", "#BBA1BA", "#8D6A8B", "#765A73", "#76576F", "#6F556A")
_colors("#F4EBF5", "#4D354C")
_colors("#302B21", "#FFFCF0", "#FFFCF1")
_colors("#8E7840", "#E6CA75", "#EACD72")
_colors("#473B25", "#FFF4CE", "#FFF7DF", "#FFF8E4")
_colors("#F6D78F", "#654B16", "#7B5A19")
_colors("#806E3F", "#E6D4A3", "#E7D59B")
_colors("#3E2633", "#FFF2F5", "#FBEFF3", "#FEF2F2")
_colors("#51303F", "#FBE0E8")
_colors("#63384C", "#F5CCD8")
_colors("#FFB8CE", "#752E43", "#8A2F4D", "#8D2F48", "#991B1B")
_colors("#8B5268", "#D493A4", "#B6657D", "#E7C4D0", "#E9CFD8", "#F2CCCC")
_colors("#233347", "#EFF6FF")
_colors("#AED2FF", "#24538C", "#3568B0")
_colors("#496785", "#C7DCF5")
_colors("#213B2D", "#F0FDF4")
_colors("#A0E6BA", "#166534")
_colors("#426D53", "#BBE5C8")
_colors("#CEB2F5", "#6B4AA5")


def is_dark_theme():
    app = QApplication.instance()
    return app is not None and app.property("yumekaiTheme") == "dark"


def theme_color(light):
    return QColor(_DARK_COLORS.get(light.upper(), light) if is_dark_theme() else light)


def theme_stylesheet(light_stylesheet):
    if not is_dark_theme():
        return light_stylesheet
    return re.sub(r"#[0-9A-Fa-f]{6}\b", lambda match: _DARK_COLORS.get(match[0].upper(), match[0]), light_stylesheet)
