# Breakdown

1. Record cpu_offload_bytes in the worker's usage stats.
2. Aggregate one model's usage rows into the summary.
3. Add `usage` to the detail response.
4. Print the summary in models inspect.
5. Remove the /usage route and its response model.
6. Describe the summary in docs/api.md and remove the /usage entry.
