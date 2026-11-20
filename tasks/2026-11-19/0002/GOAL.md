# Platform stop, compose checks and verify

Stopping the platform stops every application first, so the
applications network is never removed beneath a stopped executor. The
host config rejects a compose list with "gpu" and no "cpu" before it.
`marigold application verify` with no name checks every installed
application. Open WebUI's Ollama connection is off by default, and the
[environment] description states what the section does.

Effects:

- the --applications flag goes; platform stop then start leaves no
  stale containers
- a GPU compose list missing "cpu" fails at config load, with the fix
  in the message
- verify across installs reports with an exit status, for use from
  cron or CI
- Open WebUI stops logging Ollama connection errors
