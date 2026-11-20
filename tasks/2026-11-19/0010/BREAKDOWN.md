# Breakdown

1. Record cpu_offload_bytes in usage.
2. Aggregate one model's usage rows over a period.
3. Add the summary to the detail response, with the period as a
   parameter.
4. Print the summary in models inspect.
5. Remove the /usage route and its response model.
