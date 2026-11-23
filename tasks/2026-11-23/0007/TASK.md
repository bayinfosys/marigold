# /v1/embeddings answers with the submission's status

POST /v1/embeddings raises with the status code handle_submission
returns, as chat completions does.

Effects:

- a failed model answers 409 with its reason on both OpenAI-compatible
  endpoints
- an unknown model answers 400, as before
- api.md describes the status codes of both endpoints
