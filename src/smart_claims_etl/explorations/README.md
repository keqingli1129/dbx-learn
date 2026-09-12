# explorations

Ad-hoc notebooks only. **Nothing here is pipeline code.**

Everything in this directory is gitignored except this README (`**/explorations/**` plus a
negation in `.gitignore`), so scratch notebooks never reach the repository.

Pipeline dataset definitions live in `../transformations/{bronze,silver,gold}/`, one dataset per
file — see `../README.md`. A file placed here is not picked up by any pipeline's
`libraries.glob`, and a file placed in `transformations/` IS evaluated by the pipeline runtime,
so the split matters.
