# Breakdown

1. Move api/models.py to shared/schemas.py.
2. Change every import: the handlers under models/, shared/usage.py,
   shared/usage_models.py and the routes under api/routes/, including
   imports inside functions.
3. Change any document that names api/models.py.
