# Breakdown

1. Build the message from the caught exception at the four places
   standard_loader raises ModelNotFoundError: the tokenizer and the
   model, each for OSError and for any other exception.
