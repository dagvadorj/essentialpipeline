"""
Hello Pipeline - minimal EssentialPipeline example task.

Try the platform end to end with this file:
1. Create a project (or upload a new version) using the zipped copy of
   this folder as the project file.
2. Add a task for the project with task_type=python and
   script_path=main.py (the default script_path if left blank).
3. Trigger a run.

No third-party dependencies are required - this runs against the plain
python:3.11-slim image EssentialPipeline uses for task execution.
"""

import os
from datetime import datetime, timezone

task_id = os.environ.get('ESSENTIALPIPELINE_TASK_ID', 'unknown')
run_id = os.environ.get('ESSENTIALPIPELINE_RUN_ID', 'unknown')
now = datetime.now(timezone.utc).isoformat()

print(f"[hello-pipeline] task {task_id}, run {run_id} started at {now}")
print("[hello-pipeline] hello from inside the container!")
print("[hello-pipeline] done")
