from functools import partial
from pathlib import Path

import numpy as np
import pytest

from tests.fakes.fake_app import FakeSession

ENV = {
    "TEAM_TOKEN": "test-token",
    "OPENROUTER_API_KEY": "test-key",
    "MODEL_FAST": "test/fast",
    "MODEL_VLM": "test/vlm",
    "MODEL_PLANNER": "test/planner",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    """Tests never read .env: every required var is a fake, logs go to tmp_path."""
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def facturas_png(fixtures_dir) -> Path:
    p = fixtures_dir / "screens" / "facturas.png"
    if not p.exists():
        pytest.skip(f"{p} not captured yet (run book step 0)")
    return p


@pytest.fixture
def facturas_fb(facturas_png) -> np.ndarray:
    """h × w × 4 BGRX, like the POC's RFB.fb."""
    from PIL import Image

    rgb = np.asarray(Image.open(facturas_png).convert("RGB"))
    fb = np.zeros((*rgb.shape[:2], 4), np.uint8)
    fb[:, :, 2::-1] = rgb
    return fb


@pytest.fixture
def fake_app(fixtures_dir):
    """FakeSession factory over tests/fixtures/elements/: fake_app(start, transitions)."""
    return partial(FakeSession, elements_dir=fixtures_dir / "elements")


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    return tmp_path / "cache.sqlite"
