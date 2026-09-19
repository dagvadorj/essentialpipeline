# Hello Pipeline

An example project for EssentialPipeline - use it as your first upload to
try creating a project, adding tasks, and running them.

## Contents

- `main.py` - a minimal single-script task. Prints a message and exits 0.
- `extract.py`, `transform.py`, `load.py` - a small 3-step ETL pipeline
  over synthetic order data, showing what a project with several tasks
  looks like:
  - `extract.py` generates raw order records (`data/raw_orders.csv`),
    including a few invalid rows on purpose.
  - `transform.py` cleans them and computes `total_price`
    (`data/cleaned_orders.csv`).
  - `load.py` aggregates a small revenue report (`data/report.json`) and
    prints it.
- `pipeline_data.py` - shared helper code the three steps import, not a
  task entry point itself. Shows a project can have library code, not
  just standalone scripts.
- `requirements.txt` - empty; everything here only uses the standard
  library.
- `project.yaml` - the project manifest, listing the same four tasks
  above. Optional (a project without one still works, tasks just get
  added by hand instead) - validated on upload if present, but nothing
  yet creates tasks from it automatically, so step 2 below is still a
  manual step even with this file included.

## Using it

1. Download this as a zip and upload it when creating a new project (or
   as a new version of an existing one).
2. Add one task per script you want to run, each with task type `python`
   and the matching script path - `main.py` (the default if you leave
   script path blank), `extract.py`, `transform.py`, or `load.py`.
3. Trigger a task and check its run status/logs.

## A note on the ETL steps and state

Each task run currently executes in its own fresh container extracted
straight from this project's zip - task runs don't share a persistent
volume with each other yet (see Decision 4/Garage in the main project's
`plan.md`). So `transform.py` and `load.py` each look for the previous
step's output file first, and fall back to regenerating the same
synthetic data deterministically if it isn't there - which means every
step also works fine triggered on its own, not just as part of a chain.
