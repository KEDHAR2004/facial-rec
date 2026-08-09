"""Bundled sample imagery so the app can be demonstrated fully offline.

``scikit-image`` ships a real photograph (the ``astronaut`` sample, a portrait
of Eileen Collins) that contains a clearly detectable frontal face. Using it
means the demo needs no network access at runtime.
"""

from __future__ import annotations

import cv2
import numpy as np
from skimage import data


def astronaut_bgr() -> np.ndarray:
    """Return the scikit-image astronaut sample as an OpenCV BGR image."""

    rgb = data.astronaut()  # HxWx3, uint8, RGB
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
