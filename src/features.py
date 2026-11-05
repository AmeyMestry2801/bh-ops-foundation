"""Phase 6: model dataset and feature definitions (scheduling-time features only).

ALL DATA IS SYNTHETIC. docs/leakage_audit.md lists every excluded field and why.
"""
import duckdb
import numpy as np
import pandas as pd

from src.config import WAREHOUSE

TRAIN_END = pd.Timestamp("2025-12-31")
VAL_START, VAL_END = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-31")
TEST_START = pd.Timestamp("2026-04-01")

NUM = ["lead_days", "prior_no_show_count", "phq9_total", "gad7_total", "appt_hour",
       "sdoh_housing", "sdoh_transport", "sdoh_food", "sdoh_employment"]
CAT = ["modality", "payer_type", "age_band", "appt_dow", "provider_type", "language"]
FEATURES = NUM + CAT
TARGET = "is_no_show"

FORBIDDEN = {"status", "is_no_show", "is_late_cancel", "is_cancelled", "is_completed", "is_resolved",
             "reminder_arm", "experiment_arm", "claim_status", "denial_code", "paid_amount",
             "allowed_amount", "billed_amount", "appointment_id", "patient_id", "provider_id",
             "clinic_id", "acuity", "scheduled_ts", "appt_ts", "appt_date", "created_date", "intake_ts"}
assert not (FORBIDDEN & set(FEATURES)), "forbidden field in feature list"

DOW = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri"}

SQL = """
select f.appointment_id, f.patient_id, f.appt_date, f.lead_days, f.modality, f.appt_dow, f.appt_hour,
       f.is_no_show,
       p.payer_type, p.age_band, p.language, p.prior_no_show_count, p.phq9_total, p.gad7_total,
       p.sdoh_housing, p.sdoh_transport, p.sdoh_food, p.sdoh_employment,
       v.provider_type
from marts.fact_appointment f
join marts.dim_patient p on f.patient_id = p.patient_id
join marts.dim_provider v on f.provider_id = v.provider_id
where f.is_resolved = 1 and f.reminder_arm in ('standard', 'control')
"""


def load() -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    df = con.execute(SQL).df()
    con.close()
    df["appt_date"] = pd.to_datetime(df["appt_date"])
    df["appt_dow"] = df["appt_dow"].map(DOW)
    for c in NUM:
        df[c] = df[c].astype("float64")
    for c in CAT:
        df[c] = df[c].astype(str)
    df[TARGET] = df[TARGET].astype(int)
    d = df["appt_date"]
    df["split"] = np.select([d <= TRAIN_END, (d >= VAL_START) & (d <= VAL_END), d >= TEST_START],
                            ["train", "val", "test"], default="none")
    return df.sort_values("appointment_id").reset_index(drop=True)
