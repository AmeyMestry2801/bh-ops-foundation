"""Build notebooks/01_eda.ipynb and notebooks/02_experiment.ipynb (re-run to regenerate).
Notebooks only call src modules; logic lives in src/."""
import nbformat as nbf

from src.config import ROOT

SETUP = ("import sys, pathlib\n"
         "sys.path.insert(0, str(pathlib.Path.cwd().parent))\n"
         "import pandas as pd\n"
         "from IPython.display import Image, Markdown, display\n"
         "pd.set_option('display.width', 200)\n")


def save(nb, name):
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    (ROOT / "notebooks").mkdir(exist_ok=True)
    nbf.write(nb, str(ROOT / "notebooks" / name))
    print("wrote notebooks/" + name)


nb = nbf.v4.new_notebook()
nb.cells = [
    nbf.v4.new_markdown_cell("# 01 EDA: no-show drivers\n**All data is synthetic.** Logic lives in `src/eda.py`."),
    nbf.v4.new_code_cell(SETUP + "from src import eda"),
    nbf.v4.new_code_cell("out = eda.run()\nprint(f\"{out['df_rows']:,} resolved appointments; overall no-show {out['overall']:.1%}\")"),
    nbf.v4.new_markdown_cell("## Test results (Holm-adjusted across all tests)"),
    nbf.v4.new_code_cell("cols = ['family','variable','effect_name','effect','n','p_holm','v_one_per_patient']\nout['tests'][cols].round(4)"),
    nbf.v4.new_markdown_cell("## No-show rate by driver"),
    nbf.v4.new_code_cell("Image(filename=str(eda.FIGURES / 'eda_noshow_drivers.png'))"),
    nbf.v4.new_markdown_cell("## Rates behind the figure"),
    nbf.v4.new_code_cell("out['rates'].round(4)"),
    nbf.v4.new_markdown_cell("## Findings"),
    nbf.v4.new_code_cell("Markdown(out['findings'])"),
]
save(nb, "01_eda.ipynb")

nb = nbf.v4.new_notebook()
nb.cells = [
    nbf.v4.new_markdown_cell("# 02 Reminder experiment analysis\n**All data is synthetic; effects were planted by the generator.** "
                             "Logic lives in `src/experiment.py`; the plan is in `docs/assumptions.md` (A30-A38)."),
    nbf.v4.new_code_cell(SETUP + "from src import experiment"),
    nbf.v4.new_code_cell("out = experiment.run()\nout['rates'].round(4)"),
    nbf.v4.new_markdown_cell("## Primary effects (cluster-robust)"),
    nbf.v4.new_code_cell("e = out['effects']\n"
                         "e[(e.analysis=='primary') & e.method.str.startswith('cluster-robust')]"
                         "[['comparison','metric','estimate','ci_low','ci_high','p_raw','p_holm']].round(4)"),
    nbf.v4.new_markdown_cell("## Validity: largest covariate imbalances (SMD)"),
    nbf.v4.new_code_cell("b = out['balance'].assign(abs_smd=lambda t: t['smd'].abs())\nb.sort_values('abs_smd', ascending=False).head(10).round(3)"),
    nbf.v4.new_markdown_cell("## Power"),
    nbf.v4.new_code_cell("pd.Series(out['power']).to_frame('value')"),
    nbf.v4.new_markdown_cell("## Guardrails"),
    nbf.v4.new_code_cell("out['guardrails'].round(4)"),
    nbf.v4.new_markdown_cell("## Effects and subgroups"),
    nbf.v4.new_code_cell("Image(filename=str(experiment.FIGURES / 'experiment_effects.png'))"),
    nbf.v4.new_markdown_cell("## Decision memo"),
    nbf.v4.new_code_cell("Markdown(out['memo'])"),
]
save(nb, "02_experiment.ipynb")

nb = nbf.v4.new_notebook()
nb.cells = [
    nbf.v4.new_markdown_cell("# 03 No-show model\n**All data is synthetic.** Logic lives in `src/model.py`; this notebook only "
                             "reads the saved results (so the test set is not re-run). Rules: `docs/leakage_audit.md`, A43-A50."),
    nbf.v4.new_code_cell(SETUP + "import json\nfrom src.config import RESULTS, FIGURES\n"
                         "m = json.load(open(RESULTS / 'model_metrics.json'))"),
    nbf.v4.new_markdown_cell("## Promotion decision (rule fixed before running)"),
    nbf.v4.new_code_cell("pd.Series(m['promotion']).to_frame('value')"),
    nbf.v4.new_markdown_cell("## Test metrics"),
    nbf.v4.new_code_cell("pd.read_csv(RESULTS / 'model_test_metrics.csv').round(4)"),
    nbf.v4.new_markdown_cell("## Calibration, cumulative gain, precision-recall"),
    nbf.v4.new_code_cell("Image(filename=str(FIGURES / 'model_eval.png'))"),
    nbf.v4.new_markdown_cell("## Lift by decile"),
    nbf.v4.new_code_cell("t = pd.read_csv(RESULTS / 'lift_table.csv'); t[t.is_final].round(3)"),
    nbf.v4.new_markdown_cell("## SHAP importance"),
    nbf.v4.new_code_cell("Image(filename=str(FIGURES / 'shap_importance.png'))"),
    nbf.v4.new_markdown_cell("## Fairness slices"),
    nbf.v4.new_code_cell("display(pd.read_csv(RESULTS / 'fairness_slices.csv').round(3)); pd.read_csv(RESULTS / 'fairness_tests.csv').round(4)"),
    nbf.v4.new_markdown_cell("## Outreach simulation (assumptions A49)"),
    nbf.v4.new_code_cell("pd.DataFrame(m['simulation']['rows']).round(2)"),
]
save(nb, "03_noshow_model.ipynb")
