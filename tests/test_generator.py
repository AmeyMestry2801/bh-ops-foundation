"""Tests for the synthetic data generator (pure functions) and the raw CSVs it wrote."""
import numpy as np
import pandas as pd
import pytest

from src import generate_data as g
from src.config import DATA_RAW


def test_calibrate_intercept_hits_target_mean():
    rng = np.random.default_rng(0)
    z = rng.normal(size=5000)
    b = g.calibrate_intercept(z, 0.22)
    assert g.sigmoid(z + b).mean() == pytest.approx(0.22, abs=1e-6)


def test_sigmoid_known_values():
    assert g.sigmoid(0.0) == pytest.approx(0.5)
    assert g.sigmoid(np.log(3)) == pytest.approx(0.75)


def test_noshow_rate_excludes_cancelled():
    df = pd.DataFrame({"status": ["no_show", "completed", "completed", "cancelled", "cancelled"]})
    assert g.noshow_rate(df) == pytest.approx(1 / 3)


def test_clinics_and_providers_structure():
    rng = np.random.default_rng(0)
    clinics = g.make_clinics()
    prov = g.make_providers(rng, clinics)
    assert len(clinics) == 12 and "Buffalo" in set(clinics["city"])
    assert len(prov) == 60
    assert prov["provider_type"].value_counts().to_dict() == {"therapist": 30, "NP": 18, "psychiatrist": 12}


@pytest.mark.skipif(not (DATA_RAW / "appointments.csv").exists(), reason="run `python -m src.generate_data` first")
def test_raw_files_have_injected_dirt_and_no_names():
    a = pd.read_csv(DATA_RAW / "appointments.csv", dtype=str)
    p = pd.read_csv(DATA_RAW / "patients.csv", dtype=str)
    assert a["appointment_id"].duplicated().sum() > 0          # duplicates injected
    assert p["payer_type"].isna().sum() > 0                    # missing payer injected
    assert a["appt_ts"].str.endswith("Z").any()                # mixed timezone formats injected
    assert {"name", "first_name", "last_name"}.isdisjoint(set(p.columns))
    assert p["patient_id"].str.match(r"^P\d{6}$").all()


@pytest.mark.skipif(not (DATA_RAW / "appointments.csv").exists(), reason="run `python -m src.generate_data` first")
def test_seed_makes_generation_reproducible_for_small_tables():
    a = g.make_clinics()
    b = g.make_clinics()
    pd.testing.assert_frame_equal(a, b)
