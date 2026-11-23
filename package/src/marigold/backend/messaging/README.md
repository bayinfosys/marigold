# backend.messaging -- queue and notification backends

Implementations of the QueueBackend and NotificationBackend interfaces,
which shared/messaging.py declares, used by the platform:

- `postgres.py` -- `PostgresQueueBackend`: queue tables in the platform
  database, claimed with `SELECT ... FOR UPDATE SKIP LOCKED`.
- `local.py` -- `LocalNotificationBackend`: stores each lifecycle event
  as a `WorkerEvent` row in the events table, with no network calls or
  threads.

Import the backend you need directly.

## Usage

```python
import psycopg2

from backend.messaging.local import LocalNotificationBackend
from backend.messaging.postgres import PostgresQueueBackend

from dynawrap.backends.postgres import PostgresBackend

conn = psycopg2.connect(dsn)

queue = PostgresQueueBackend(conn)
queue.create_queue("my-queue")

PostgresBackend.create_table(conn, "events")
notifications = LocalNotificationBackend(PostgresBackend(conn), "events")
```
