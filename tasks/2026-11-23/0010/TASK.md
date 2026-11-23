# Queue and notification interfaces in shared/

The QueueBackend and NotificationBackend interfaces move from
backend/messaging/base.py to shared/messaging.py, and every import of
them changes.

Effects:

- shared/ no longer imports from backend/; the backends implement
  interfaces declared in shared/
- no behaviour changes
