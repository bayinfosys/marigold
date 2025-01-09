# BayIS VecMDL

Models for embedding data, working with embeddings, and converting embeddings to outputs.


# cache libraries

models require library code which is cached in `./cache/packages` and mounted into the containers.
These packages are loaded to an AWS EFS which is mounted into the AWS lambda, and how the lambda functions run pytorch, huggingface, etc which all exceed the 10Gb container size limit.

the cache is built via a container which controls the scripts and mounts to do the job properly (this container matches the ec2 instance which builds the AWS EFS cache, so must be in-sync):
```bash
make build/tools/local-cache-builder && make build/local-cache
```

# cache models

models are cached from huggingface to local disk and replicates the AWS EFS/AWS Lambda environment.
To build the cache locally run:
```bash
make build/cache
```

this builds all the model type caches. Each of these can be cached in isolation with:
```bash
make build/cache/instruct
make build/cache/img2txt
```
and so on.

specific models can be cached by adding them to the cache type parameter:
```bash
make build/cache/instruct/qwen/qwen2-0.5b-instruct
make build/cache/instruct/qwen/qwen2-1.5b-instruct
```
and so on. The model name corresponds to the model name on huggingface in all lowercase.

**NB**: avoid building the entire cache because the download is long, and the storage requirements are significant.
**NB**: models must load into less than 10Gb of ram (ideally less). The `cache_model.py` script outputs the memory used by loading a model at the end of the cache process.
