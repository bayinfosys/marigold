terraform {
  backend "s3" {
    bucket = "tf.bayis.co.uk"
    key    = "state/embedding/tools-cache-builder.tfstate"
    region = "eu-west-2"
  }
}

provider "aws" {
  region = "eu-west-2"
}

data "terraform_remote_state" "containers" {
  backend = "s3"
  config = {
    bucket = "tf.bayis.co.uk"
    key    = "state/embedding/01-containers.tfstate"
    region = "eu-west-2"
  }
}

data "terraform_remote_state" "pipelines" {
  backend = "s3"
  config = {
    bucket = "tf.bayis.co.uk"
    key    = "state/embedding/02-lambdas.tfstate"
    region = "eu-west-2"
  }
}
