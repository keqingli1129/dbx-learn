# smart_claims_etl — pipeline source

Files here are **evaluated by the Lakeflow pipeline runtime**, not imported. They are picked up
by the `libraries.glob` in each pipeline resource under `resources/`, so anything matching the
glob is treated as a dataset definition.

Conventions:

- **One dataset per file**, named after the dataset it defines.
- Raw `.py` / `.sql` files, not notebooks.
- Use the modern API: `from pyspark import pipelines as dp`. Never `import dlt`, `LIVE.`,
  or `APPLY CHANGES` (Constitution VI).
- Business logic is **imported** from `smart_claims.lib`, never written inline in a `@dp.table`
  body (Constitution II). That import works because each pipeline declares
  `--editable ${workspace.file_path}` in its `environment.dependencies`.

`transformations/` is the pipeline source. `explorations/` is for ad-hoc notebooks only and is
excluded from git by `**/explorations/**` in .gitignore — nothing there is pipeline code.

Layout mirrors the medallion layers; `bronze/` is owned by the ingest pipeline, `silver/` and
`gold/` by the transform pipeline (Constitution III: one writer per table).
