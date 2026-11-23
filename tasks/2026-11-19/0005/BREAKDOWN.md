# Breakdown

1. Give LocalNotificationBackend the table backend, and save each
   published event as a WorkerEvent row.
2. Order the WorkerEvent sort key by timestamp, then event type.
3. Construct the backend with the table backend in the worker and in
   the API, and pass the app's backend from the OpenAI routes, which
   pass None today.
4. Remove the unused duplicate in backend/local/events.py.
5. Add the resolved settings with sources, footprint, dtype, placement
   on each device and error to the load event payloads.
6. Describe the events, their payloads and their table in
   architecture.md.
