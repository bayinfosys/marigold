"""dynawrap.messaging -- queue and notification backends.

Provides QueueBackend and NotificationBackend interfaces with implementations
for AWS (SQS/SNS) and PostgreSQL. Import the backend you need directly to
avoid pulling in unnecessary dependencies.

Usage::

    # AWS
    from dynawrap.messaging.sqs_sns import SQSQueueBackend, SNSNotificationBackend

    # Postgres
    from dynawrap.messaging.postgres import PostgresQueueBackend, PostgresNotificationBackend

Setup (Postgres)::

    import psycopg2
    conn = psycopg2.connect(dsn)

    queue = PostgresQueueBackend(conn)
    queue.create_queue("my-queue")

    notifications = PostgresNotificationBackend(dsn)
    notifications.create_topic("lifecycle")
    notifications.start_repeater()

Setup (AWS / LocalStack)::

    queue = SQSQueueBackend(endpoint_url="http://localhost:4566")
    queue.create_queue("my-queue")

    notifications = SNSNotificationBackend(endpoint_url="http://localhost:4566")
    notifications.create_topic("lifecycle")
"""
