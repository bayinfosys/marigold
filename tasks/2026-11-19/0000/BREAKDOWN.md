# Breakdown

1. Apply the model's settings inside the load, so an error there takes
   the load-failure path: the event, the drained queue, failed_reason.
2. Record the keys each model sets, and clear them along with the
   loader keys before the next model's settings apply.
3. Build the VRAM failure message from the off-GPU tensor count and
   bytes, the on-GPU bytes, and free and total memory per device; use
   it for both the log line and the exception.
