# `databricks jobs submit` — one-off runs

Reference for running code on Databricks **without** declaring a job. Everything below was
verified against this workspace while debugging the import failure recorded in
[research R15](001-smart-claims/research.md).

Use it for probes, diagnostics and one-off experiments. For anything that must be findable,
re-runnable or scheduled, declare a job resource in `resources/*.job.yml` and use
`databricks bundle run <key>` instead — ephemeral runs **do not appear in the Jobs UI**, which
the API documents explicitly.

---

## Minimal working payload

```json
{
  "run_name": "seed-source-data",
  "environments": [
    {
      "environment_key": "default",
      "spec": {
        "environment_version": "5",
        "dependencies": [
          "/Workspace/Users/<you>/.bundle/smart_claims/dev/artifacts/.internal/smart_claims-0.0.1-py3-none-any.whl"
        ]
      }
    }
  ],
  "tasks": [
    {
      "task_key": "seed",
      "environment_key": "default",
      "spark_python_task": {
        "python_file": "/Workspace/Users/<you>/.bundle/smart_claims/dev/files/src/smart_claims/setup/seed_source_data.py",
        "source": "WORKSPACE",
        "parameters": ["--catalog", "smart_claims_dev",
                       "--source-schema", "dev_keqingli1129_source"]
      }
    }
  ]
}
```

## Submit, poll, read output

```bash
PROFILE=DEFAULT

# 1. submit -- returns immediately with a run_id
RID=$(databricks jobs submit --json @payload.json --profile $PROFILE --no-wait -o json \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["run_id"])')

# 2. poll the JOB run until it leaves PENDING/RUNNING
until databricks jobs get-run $RID --profile $PROFILE -o json \
      | python3 -c 'import sys,json;s=json.load(sys.stdin)["state"]["life_cycle_state"];print(s);exit(0 if s in ("TERMINATED","INTERNAL_ERROR","SKIPPED") else 1)'; do
  sleep 12
done

# 3. output lives on the TASK run, not the job run -- get its id first
TRID=$(databricks jobs get-run $RID --profile $PROFILE -o json \
       | python3 -c 'import sys,json;print(json.load(sys.stdin)["tasks"][0]["run_id"])')

databricks jobs get-run-output $TRID --profile $PROFILE -o json
```

**The two-id distinction is the most common mistake.** `get-run-output` takes the **task** run id.
Passing the job run id returns metadata with an empty `notebook_output` and no error.

## Task-type variants

Swap the `spark_python_task` block for any of these:

```json
"notebook_task":     { "notebook_path": "/Workspace/.../nb",
                       "base_parameters": {"catalog": "smart_claims_dev"} }

"python_wheel_task": { "package_name": "smart_claims",
                       "entry_point": "main",
                       "parameters": ["--catalog", "smart_claims_dev"] }

"sql_task":          { "warehouse_id": "cdcb7003ae7dd5ab",
                       "query": {"query_id": "..."} }

"pipeline_task":     { "pipeline_id": "..." }
```

## Gotchas, all hit for real

| Gotcha | Detail |
|---|---|
| **Wheel path** | The wheel uploads to `${workspace.artifact_path}/.internal/`, **not** `files/dist/`. A bundle-declared resource writes `../dist/*.whl` and the CLI rewrites the path at deploy time; `jobs submit` gets no rewriting, so name the real uploaded path. Guessing wrong yields *"Library installation failed ... The library file does not exist"* |
| **`--editable` does not work** | `dependencies: ["--editable ${workspace.file_path}"]` installs "successfully" but writes a `.pth` containing a doubled `/Workspace/Workspace/...` prefix. `pip list` shows the package; `import` fails for any script not run from `src/` itself. Use the wheel — research R15 |
| **Output capture** | `print()` goes to `logs`. To return a value, call `dbutils.notebook.exit(json.dumps(...))` and read `notebook_output.result` |
| **`SystemExit: 0` marks the task FAILED** | Any `SystemExit` counts as failure to the runner, including `--help` exiting cleanly. Check the logs before believing the status |
| **`cwd` is the script's own directory** | Not the project root. This is why the editable-install breakage only shows up for nested entry points |
| **`environment_version: "5"` is Python 3.12.3** | The default *notebook* serverless environment is 3.11.10. They differ; do not assume one figure covers both |

## Finding the wheel path

```bash
databricks workspace list \
  /Workspace/Users/<you>/.bundle/smart_claims/dev/artifacts/.internal --profile DEFAULT
```

## Six ways to run code, and when each fits

| Way | Persistent definition? | Appears in UI? | Use for |
|---|---|---|---|
| `bundle run <job>` | yes (`*.job.yml`) | yes | scheduled / orchestrated work |
| `bundle run <pipeline>` | yes (`*.pipeline.yml`) | yes | Lakeflow pipelines |
| **`jobs submit`** | **no** | **no** | probes, diagnostics, one-offs |
| SQL on a warehouse | no | query history | DDL the REST API refuses, e.g. `bootstrap.sh` |
| Notebook in the UI | no | yes | interactive exploration |
| `databricks-connect` locally | no | no | `workspace`-marked integration tests |
