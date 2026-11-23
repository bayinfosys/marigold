# QueueRunner sleeps between empty polls

QueueRunner sleeps one second after an empty poll that does not end
the run. The idle timeout is measured as before.

Effects:

- an idle worker sends Postgres one receive query a second, where it
  sent them without pause for the length of the idle timeout
- a message arriving on an empty queue waits at most one second
