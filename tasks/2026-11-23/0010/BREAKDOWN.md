# Breakdown

1. Move backend/messaging/base.py to shared/messaging.py.
2. Change every import: the backends under backend/messaging/,
   models/worker.py, shared/receiver_logic.py and shared/catalogue.py.
3. Change backend/messaging/README.md, which names base.py.
