# Breakdown

1. Write the catalogue row from models.yaml without carrying
   failed_reason over; update the docstring.
2. Treat a stored "error" status as a miss in the request path, and
   resubmit the request.
3. Log the catalogue item count at DEBUG.
4. Update the failure paragraph in architecture.md.
