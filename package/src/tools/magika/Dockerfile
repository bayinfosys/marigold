#
# magika google file identification model
# https://github.com/google/magika
#
FROM public.ecr.aws/lambda/python:3.9

# install the google magika package
RUN pip install magika


COPY package/src/shared.py .
COPY package/src/tools/magika/main.py .

CMD ["main.lambda_handler"]
