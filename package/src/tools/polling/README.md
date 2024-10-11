# Submit-and-poll lambda

This lambda reads the submission of data to an apigw endpoint and sends it on to the consumer with an id.
The id is logged in a dynamodb table with a "status=PENDING".
A second endpoint can poll an endpoint to read from dynamodb.

This allows us to submit work to apigw and poll for completion.
