# Local cache builder

This docker image is the container for building the model environment cache on the local host.

We use a specific python version so we need a container.
Virtualenv will only reuse the host python version (2 or 3), and we cannot specifiy the minor type of python (3.11, 3.12, etc).

And we don't want to use conda.
