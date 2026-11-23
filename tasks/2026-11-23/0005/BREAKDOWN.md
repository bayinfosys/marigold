# Breakdown

1. Add a one-second poll interval constant to models/worker.py and
   sleep for it after an empty poll that does not exit.
2. Describe the interval in QueueRunner.run's docstring.
