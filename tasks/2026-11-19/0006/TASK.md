# Model detail from the API

The existing model detail route, GET /models/{type}/{name}, returns a
model's resolved settings with their sources and its recent events
alongside the catalogue entry.

Effects:

- one request answers what applies to a model and what has happened
  to it
- the API gains no new routes
- docs/api.md describes the response
