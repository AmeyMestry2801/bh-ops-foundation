"""Leakage guard and sanity checks for the model feature set."""
from src import features as F


def test_no_forbidden_field_is_a_feature():
    assert not (F.FORBIDDEN & set(F.FEATURES))


def test_outcome_and_treatment_never_in_features():
    for bad in ("status", "is_no_show", "reminder_arm", "experiment_arm", "claim_status", "paid_amount"):
        assert bad not in F.FEATURES


def test_time_split_boundaries_do_not_overlap():
    assert F.TRAIN_END < F.VAL_START <= F.VAL_END < F.TEST_START
