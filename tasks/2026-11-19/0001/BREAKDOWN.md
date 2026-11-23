# Breakdown

1. Write the catalogue row in register_model from models.yaml without
   carrying failed_reason over; update its docstring.
2. Treat a stored "error" status as a miss in receiver_logic, and
   resubmit the request.
3. Log the catalogue item count at DEBUG.
4. Describe in architecture.md how a failure is recorded, what the
   API returns for a failed model, and that populate clears it.
