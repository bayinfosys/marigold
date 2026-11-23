# The catalogue in shared/

models/catalogue.py moves to shared/catalogue.py, and every import of
it changes.

Effects:

- the API, the CLI and shared/receiver_logic.py no longer import from
  the worker's package
- no behaviour changes
