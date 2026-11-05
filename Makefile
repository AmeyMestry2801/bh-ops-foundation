PY = .venv/bin/python
DBT = .venv/bin/dbt

.PHONY: data pipeline test analysis bi all clean

data:
	$(PY) -m src.generate_data

pipeline:
	$(PY) -m src.pipeline

test:
	cd dbt_project && ../$(DBT) test --profiles-dir .

analysis:
	$(PY) -m src.kpis
	$(PY) -m src.eda
	$(PY) -m src.experiment
	$(PY) -m src.model

bi:
	$(PY) -m src.export_bi

all: data pipeline test analysis bi

clean:
	rm -rf data/raw/*.csv warehouse/ops.duckdb dbt_project/target dbt_project/logs
