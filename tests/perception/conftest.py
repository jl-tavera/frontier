import numpy as np
import pytest
from PIL import Image


@pytest.fixture
def facturas_live_fb(fixtures_dir) -> np.ndarray:
    """The live v4.2 Facturas screen, BGRX: its header row is drawn as bordered boxes; a menu is open over the heading."""
    rgb = np.asarray(Image.open(fixtures_dir / "screens" / "facturas_live.png").convert("RGB"))
    fb = np.zeros((*rgb.shape[:2], 4), np.uint8)
    fb[:, :, 2::-1] = rgb
    return fb
