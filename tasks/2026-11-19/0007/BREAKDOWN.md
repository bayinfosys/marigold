# Breakdown

1. Give the local notification backend the table backend, and save
   each published event as a WorkerEvent row.
2. Order the event sort key by timestamp, then event type.
3. Construct the backend with the table backend in the worker and in
   the API.
4. Add resolved settings, footprint, dtype, placement and error to the
   load event payloads.
