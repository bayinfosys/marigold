PROJECT_NAME=vecmdl

# 3.6Gb 2.87G 1.84G
#SENTENCE_TRANSFORMERS=sentence-transformers/labse sentence-transformers/paraphrase-multilingual-mpnet-base-v2 sentence-transformers/paraphrase-multilingual-minilm-l12-v2 sentence-transformers/all-minilm-l6-v2 intfloat/e5-small-v2 intfloat/e5-small-unsupervised intfloat/multilingual-e5-small intfloat/multilingual-e5-large-instruct intfloat/e5-large-unsupervised sentence-transformers/sentence-t5-large snowflake/snowflake-arctic-embed-xs snowflake/snowflake-arctic-embed-m taylorai/gte-tiny taylorai/bge-micro-v2 whereisai/uae-large-v1 sentence-transformers/gtr-t5-large sentence-transformers/all-minilm-l12-v2 sentence-transformers/paraphrase-multilingual-mpnet-base-v2
SENTENCE_TRANSFORMERS=sentence-transformers/all-minilm-l6-v2
IMAGE_TRANSFORMERS=sentence-transformers/clip-ViT-L-14 sentence-transformers/clip-vit-b-32-multilingual-v1 sentence-transformers/clip-vit-b-32
#IMAGE_TRANSFORMERS=google/vit-base-patch16-224-in21k facebook/vit-mae-base openai/imagegpt-small facebook/dino-vitb8 facebook/dinov2-small

# 16Gb
# https://huggingface.co/microsoft
#INSTRUCTS=microsoft/phi-2 microsoft/DialoGPT-small tiiuae/falcon-7b-instruct mistralai/mixtral-8x7b-instruct-v0.1 mistralai/Mixtral-8x22B-Instruct-v0.1 mistralai/Mistral-7B-Instruct-v0.2 stabilityai/stable-code-3b stabilityai/stablelm-2-1_6b-chat google/gemma-2b-it google/gemma-7b-it HuggingFaceH4/zephyr-7b-gemma-v0.1 mosaicml/mpt-7b-instruct databricks/dolly-v2-3b meta-llama/meta-llama-3-8b-instruct

# 1B models
# NB: these models need keys:
#INSTRUCTS=apple/openelm-1_1b-instruct apple/openelm-3b-instruct
#INSTRUCTS=microsoft/phi-2 microsoft/phi-3-mini-128k-instruct llmware/bling-falcon-1b-0.1 cognitivecomputations/tinydolphin-2.8-1.1b unfilteredai/unfilteredai-1b microsoft/phi-3-mini-128k-instruct huggingfacetb/smollm-360m-instruct facebook/blenderbot-400M-distill microsoft/phi-3.5-vision-instruct
INSTRUCTS=qwen/qwen2-0.5b-instruct qwen/qwen2-1.5b-instruct qwen/qwen2.5-0.5b-instruct qwen/qwen2.5-3b-instruct microsoft/phi-3-mini-128k-instruct llmware/bling-sheared-llama-1.3b-0.1 microsoft/phi-3-mini-128k-instruct microsoft/phi-3.5-mini-instruct meta-llama/llama-3.2-1b-instruct meta-llama/llama-3.2-3b-instruct chuanli11/llama-3.2-3b-instruct-uncensored tiiuae/falcon-mamba-7b-instruct h2oai/h2o-danube3.1-4b-chat

# image generative models
#TXT2IMG=unfilteredai/nsfw-gen-v2.1 stabilityai/sdxl-turbo stabilityai/stable-diffusion-2-1 playgroundai/playground-v2.5-1024px-aesthetic sd-community/sdxl-flash-mini compvis/ldm-text2im-large-256 runwayml/stable-diffusion-v1-5 dream-textures/texture-diffusion black-forest-labs/flux.1-schnell
TXT2IMG=sd-community/sdxl-flash stabilityai/sd-turbo

# image to text, OCR etc
#IMG2TXT=llava-hf/llava-onevision-qwen2-0.5b-ov-hf jinhybr/OCR-Donut-CORD naver-clova-ix/donut-base-finetuned-docvqa vikhyatk/moondream2 unsloth/llama-3.2-11b-vision-instruct-bnb-4bit h2oai/h2ovl-mississippi-2b
IMG2TXT=qwen/qwen2-vl-7b-instruct huggingfacetb/smolvlm-instruct

# image segmentation
IMG2SEG=cidas/clipseg-rd64-refined

# music generation models
TXT2MUSID=facebook/musicgen-stereo-small

# text to speech
# see: https://huggingface.co/models?sort=trending&search=facebook%2Fmms-tts
#      https://dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html
#TXT2SPEECH=facebook/mms-tts-eng facebook/mms-tts-tha facebook/mms-tts-yor facebook/mms-tts-som facebook/mms-tts-mon facebook/mms-tts-abi facebook/mms-tts-abp facebook/mms-tts-bmr facebook/mms-tts-aca facebook/mms-tts-cwe facebook/mms-tts-hak facebook/mms-tts-bmu facebook/mms-tts-kjg facebook/mms-tts-acd facebook/mms-tts-cwt facebook/mms-tts-mai facebook/mms-tts-hap facebook/mms-tts-myx facebook/mms-tts-por facebook/mms-tts-bmv facebook/mms-tts-cya facebook/mms-tts-ace facebook/mms-tts-sqi facebook/mms-tts-kjh facebook/mms-tts-cym
TXT2SPEECH=facebook/mms-tts-eng facebook/mms-tts-cym facebook/mms-tts-deu facebook/mms-tts-fra facebook/mms-tts-spa facebook/mms-tts-fin facebook/mms-tts-nld

# text to model
TXT2MODEL=openai/shap-e

# upscalers
UPSCALER=compvis/ldm-super-resolution-4x-openimages

# depth estimation
DEPTH=facebook/dpt-dinov2-small-kitti intel/dpt-large intel/dpt-hybrid-midas vinvino02/glpn-nyu

# tools for processing content
# magicka: file identifer from google
TOOLS=magika
# FIXME: add facebook/nougat-small to convert pdf to markdown
# FIXME: add pdf to image (via libreoffice)

AWS_ACCOUNT_ID=789643290641
AWS_REGION=eu-west-2

# tag can be set on the commandline to specifcy the tag used in terraform commands, i.e.:
# make LAYER=layer-01 TAG=v0.2-9-g195d3c1 plan
TAG?=$(shell git describe --tags)


# check vars
ifeq ($(TAG),)
    $(error TAG is not set)
endif

#
# model environment
# common container to cache and host model binaries
# model binaries are cached on the host/efs and mounted into this container
# model packages (torch etc) are also on the host/etfs and mounted
#
.PHONEY:
build/environment:
	docker build \
	  -t $(PROJECT_NAME)/environment:$(TAG) \
	  -f package/src/models/environment/Dockerfile .

push/environment:
	docker tag \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/environment:$(TAG) && \
	docker push $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/environment:$(TAG) && \
	docker rmi $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/environment:$(TAG)

#
# text embeddings
#
cache/text-embedding/%:
	# cache the model locally by mounting a local dir into the container and running commands
	# python packages are mounted into /host
	# on aws lambda we put these files into efs and mount into the same mount points for the lambda
	docker run \
	  -it \
	  --rm \
	  --entrypoint python3 \
	  -e HF_HUB_OFFLINE=0 \
	  -e HF_HUB_DISABLE_PROGRESS_BARS=0 \
	  -e MODEL_TYPE="text-embedding" \
	  -e MODELNAME=$* \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e LOCAL_FILES_ONLY=0 \
	  -v ./cache/models:/models \
	  -v ./cache/packages:/host:ro \
	  -e PYTHONPATH=/usr/local/lib/python3.12:/host/python3.12/site-packages/ \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  models/cache_model.py

cache/text-embedding: build/environment $(addprefix cache/text-embedding/,$(SENTENCE_TRANSFORMERS))


#
# instructs
#
cache/instruct/%:
	# cache the model locally by mounting a local dir into the container and running commands
	# python packages are mounted into /host
	# on aws lambda we put these files into efs and mount into the same mount points for the lambda
	docker run \
	  -it \
	  --rm \
	  --entrypoint python3 \
	  -e HF_HUB_OFFLINE=0 \
	  -e HF_HUB_DISABLE_PROGRESS_BARS=0 \
	  -e HF_TOKEN=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 \
	  -e MODEL_TYPE="instruct" \
	  -e MODELNAME=$* \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e LOAD_IN_4BIT=0 \
	  -e LOCAL_FILES_ONLY=0 \
	  -v ./cache/models:/models \
	  -v ./cache/packages:/host:ro \
	  -e PYTHONPATH=/usr/local/lib/python3.12:/host/python3.12/site-packages/ \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  models/cache_model.py


cache/instruct: build/environment $(addprefix cache/instruct/,$(INSTRUCTS))


#
# tts
#
cache/tts/%:
	docker run \
	  -it \
	  --rm \
	  --entrypoint python3 \
	  -e HF_HUB_OFFLINE=0 \
	  -e HF_HUB_DISABLE_PROGRESS_BARS=0 \
	  -e MODEL_TYPE="tts" \
	  -e MODELNAME=$* \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e LOAD_IN_4BIT=0 \
	  -e LOCAL_FILES_ONLY=0 \
	  -v ./cache/models:/models \
	  -v ./cache/packages:/host:ro \
	  -e PYTHONPATH=/usr/local/lib/python3.12:/host/python3.12/site-packages/ \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  models/cache_model.py

cache/tts: build/environment $(addprefix cache/tts/,$(TXT2SPEECH))


# image embedding
cache/image-embedding/%:
	docker run \
	  -it \
	  --rm \
	  --entrypoint python3 \
	  -e HF_HUB_OFFLINE=0 \
	  -e HF_HUB_DISABLE_PROGRESS_BARS=0 \
	  -e MODEL_TYPE="image-embedding" \
	  -e MODELNAME=$* \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e LOCAL_FILES_ONLY=0 \
	  -v ./cache/models:/models \
	  -v ./cache/packages:/host:ro \
	  -e PYTHONPATH=/usr/local/lib/python3.12:/host/python3.12/site-packages/ \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  models/cache_model.py

cache/image-embedding: $(addprefix cache/image-embedding/,$(IMAGE_TRANSFORMERS))


# iamge generators
cache/txt2img/%:
	docker run \
	  -it \
	  --rm \
	  --entrypoint python3 \
	  -e HF_HUB_OFFLINE=0 \
	  -e HF_HUB_DISABLE_PROGRESS_BARS=0 \
	  -e MODEL_TYPE="txt2img" \
	  -e MODELNAME=$* \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e LOCAL_FILES_ONLY=0 \
	  -v ./cache/models:/models \
	  -v ./cache/packages:/host:ro \
	  -e PYTHONPATH=/usr/local/lib/python3.12:/host/python3.12/site-packages/ \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  models/cache_model.py

cache/txt2img: $(addprefix cache/txt2img/,$(TXT2IMG))

# imaget-to-text
cache/img2txt/%:
	docker run \
	  -it \
	  --rm \
	  --entrypoint python3 \
	  -e HF_HUB_OFFLINE=0 \
	  -e HF_HUB_DISABLE_PROGRESS_BARS=0 \
	  -e HF_TOKEN=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 \
	  -e MODEL_TYPE="img2txt" \
	  -e MODELNAME=$* \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e LOCAL_FILES_ONLY=0 \
	  -v ./cache/models:/models \
	  -v ./cache/packages:/host:ro \
	  -e PYTHONPATH=/usr/local/lib/python3.12:/host/python3.12/site-packages/ \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  models/cache_model.py

cache/img2txt: $(addprefix cache/img2txt/,$(IMG2TXT))


cache/depth/%:
	docker run \
	  -it \
	  --rm \
	  --entrypoint python3 \
	  -e HF_HUB_OFFLINE=0 \
	  -e HF_HUB_DISABLE_PROGRESS_BARS=0 \
	  -e MODEL_TYPE="depth" \
	  -e MODELNAME=$* \
	  -e CACHE_DIR=/models \
	  -e HF_HUB_CACHE=/models \
	  -e LOCAL_FILES_ONLY=0 \
	  -v ./cache/models:/models \
	  -v ./cache/packages:/host:ro \
	  -e PYTHONPATH=/usr/local/lib/python3.12:/host/python3.12/site-packages/ \
	  $(PROJECT_NAME)/environment:$(TAG) \
	  models/cache_model.py


cache/depth: $(addprefix cache/depth/,$(DEPTH))


#
# cache models command
#
cache: cache/text-embedding cache/instruct cache/tts cache/txt2img cache/image-embedding cache/depth

#
# tools
#
build/tools/%:
	docker build \
	  -t $(PROJECT_NAME)/tools/$*:$(TAG) \
	  -f package/src/tools/$*/Dockerfile .

push/tools/%:
	docker tag \
	  $(PROJECT_NAME)/tools/$*:$(TAG) \
	  $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/tools/$*:$(TAG) && \
	docker push $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/tools/$*:$(TAG) && \
	docker rmi $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com/bayis/$(PROJECT_NAME)/tools/$*:$(TAG)

build/tools: $(addprefix build/tools/,$(TOOLS))
push/tools: $(addprefix push/tools/,$(TOOLS))

build/local-cache:
	# run make build/tools/local-cache-builder to create the image
	docker run -it \
	  -v $(shell pwd)/cache/packages/python3.12/site-packages:/host-packages \
	  $(PROJECT_NAME)/tools/local-cache-builder:$(TAG)

docker-login:
	@echo "Logging into Amazon ECR..."
	aws ecr get-login-password --region $(AWS_REGION) | \
	docker login --username AWS --password-stdin $(AWS_ACCOUNT_ID).dkr.ecr.$(AWS_REGION).amazonaws.com

build: build/environment build/tools
push: push/environment push/tools

#
# docker compose for local
#
run:
	# docker compose up --build --abort-on-container-exit --remove-orphans
	GIT_TAG=$(shell git describe --tags) docker compose up --abort-on-container-exit --remove-orphans

stop:
	docker compose stop
	docker compose rm


#
# terraform
# + LAYER=01-containers make init
# + LAYER=01-containers make plan
# + LAYER=01-containers make apply
# + make build-all && make push-all
# + make api
# + LAYER=02-lambdas init
# + LAYER=02-lambdas plan
# + LAYER=02-lambdas apply
#

#
# swagger api definition is stored in s3
#
build/api-definition:
	docker run -it --rm \
	  -v $(shell pwd)/package/src/api:/app/routes:ro \
	  -v $(shell pwd)/tf/03/rest:/out \
	  aws-tools/openapi_extract:v0.1 \
	    --router routes.routes:router \
	    --out-public /out/api_public_definition.json \
	    --out-private /out/api_private_definition.json \
	    --version $(TAG)

#
# model definitions are a flat json file stored in s3
#
build/models-definition: build/model_extract
	docker run -it --rm \
	  -v $(shell pwd)/package/src/api:/app/api:ro \
	  -v $(shell pwd)/package/src/models:/app/models:ro \
	  -v $(shell pwd)/tf/03-apigw/rest:/out \
	  vec/tools/model_extract:$(TAG) \
	    --out /out/models.json

#
# build all the file artefacts deployed to s3
#
build/deployment-artefacts: build/api-definition build/models-definition


.ONESHELL:
ENV ?= dev

check-layer:
	@if [ -z "$(LAYER)" ]; then \
	  echo "Error: LAYER variable is not set."; \
	  exit 1; \
	fi

init: check-layer
	terraform -chdir=tf/$(LAYER) init --upgrade
validate:
	terraform -chdir=tf/$(LAYER) validate
plan:
	terraform -chdir=tf/$(LAYER) refresh -var-file=../common.tfvars -var-file=../$(ENV).tfvars
	terraform -chdir=tf/$(LAYER) plan -var-file=../common.tfvars -var-file=../$(ENV).tfvars -out new.plan
apply:
	terraform -chdir=tf/$(LAYER) apply -parallelism=0 new.plan && rm tf/$(LAYER)/new.plan
destroy:
	terraform -chdir=tf/$(LAYER) destroy -var-file=../common.tfvars -var-file=../$(ENV).tfvars" -auto-approve
get-key:
	terraform -chdir=tf/03 output -raw api_key_value
get-asset-bucket:
	terraform -chdir=tf/02 output -raw asset_bucket_name
get-api-spec:
	terraform -chdir=tf/03 output -raw api_spec
