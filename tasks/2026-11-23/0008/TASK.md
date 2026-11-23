# Request and response schemas in shared/

api/models.py moves to shared/schemas.py, and every import of it
changes.

Effects:

- the handlers, shared/usage.py and shared/usage_models.py no longer
  import from the API package
- 21 of the 27 imports against the layers go
- no behaviour changes
