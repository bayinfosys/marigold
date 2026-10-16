# backend.messaging -- queue and notification backends

QueueBackend and NotificationBackend interfaces (`base.py`), with the
implementations the platform uses:

- `postgres.py` -- `PostgresQueueBackend`: queue tables in the platform
  database, claimed with `SELECT ... FOR UPDATE SKIP LOCKED`.
- `local.py` -- `LocalNotificationBackend`: logs lifecycle events at
  DEBUG level, with no network calls, threads or tables.

Import the backend you need directly.

## Usage

```python
import psycopg2

from backend.messaging.local import LocalNotificationBackend
from backend.messaging.postgres import PostgresQueueBackend

conn = psycopg2.connect(dsn)

queue = PostgresQueueBackend(conn)
queue.create_queue("my-queue")

notifications = LocalNotificationBackend()
```
