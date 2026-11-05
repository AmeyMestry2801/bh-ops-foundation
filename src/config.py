"""Shared configuration. Every script imports SEED and paths from here."""
from pathlib import Path
import random
import numpy as np

SEED = 42

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_STAGING = ROOT / "data" / "staging"
WAREHOUSE = ROOT / "warehouse" / "ops.duckdb"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
BI = ROOT / "bi"
RESULTS = ROOT / "results"

DATA_START = "2025-01-01"
DATA_END = "2026-06-30"
EXPERIMENT_START = "2025-10-01"
EXPERIMENT_END = "2026-03-31"


def set_seed(seed: int = SEED) -> np.random.Generator:
    """Seed python and numpy; return a numpy Generator for new-style sampling."""
    random.seed(seed)
    np.random.seed(seed)
    return np.random.default_rng(seed)
