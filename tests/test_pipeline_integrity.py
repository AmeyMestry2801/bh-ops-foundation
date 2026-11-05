"""Integration tests on the built warehouse. Skipped if the warehouse has not been built."""
import duckdb
import pytest

from src.config import WAREHOUSE

pytestmark = pytest.mark.skipif(not WAREHOUSE.exists(), reason="run `python -m src.pipeline` first")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(WAREHOUSE), read_only=True)
    yield c
    c.close()


def one(con, sql):
    return con.execute(sql).fetchone()[0]


def test_no_duplicate_keys_in_marts(con):
    assert one(con, "select count(*) - count(distinct appointment_id) from marts.fact_appointment") == 0
    assert one(con, "select count(*) - count(distinct claim_id) from marts.fact_claim") == 0
    assert one(con, "select count(*) - count(distinct patient_id) from marts.dim_patient") == 0


def test_all_payers_standardized(con):
    vals = {r[0] for r in con.execute("select distinct payer_type from marts.dim_patient").fetchall()}
    assert vals <= {"Medicaid", "Medicare", "Commercial", "Self-pay", "Unknown"}


def test_utc_timestamps_normalized_to_business_hours(con):
    lo, hi = con.execute("select min(appt_hour), max(appt_hour) from marts.fact_appointment").fetchone()
    assert (lo, hi) == (9, 17)


def test_claim_amount_rule(con):
    assert one(con, "select count(*) from marts.fact_claim where paid_amount > allowed_amount "
                    "or allowed_amount > billed_amount") == 0


def test_experiment_assignment_integrity(con):
    # one arm per patient and appointment arms match the assignment inside the window
    assert one(con, "select count(*) - count(distinct patient_id) from staging.stg_experiment_assignments") == 0
    assert one(con, """select count(*) from marts.fact_appointment f join marts.dim_patient p using (patient_id)
                       where f.reminder_arm <> 'standard' and p.experiment_arm is distinct from f.reminder_arm""") == 0


def test_every_patient_has_intake(con):
    assert one(con, "select count(*) from marts.dim_patient where intake_ts is null") == 0
