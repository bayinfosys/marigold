terraform {
  backend "s3" {
    bucket = "tf.bayis.co.uk"
    key = "state/embedding/03-apigw.tfstate"
    region = "eu-west-2"
  }
}

provider "aws" {
  region = "eu-west-2"
}

provider "aws" {
  alias = "us_east"
  region = "us-east-1"
}


# remote backend from previous layer
data "terraform_remote_state" "containers" {
  backend = "s3"  # or other backend used to store state
  config = {
    bucket = "tf.bayis.co.uk"
    key = "state/embedding/01-containers.tfstate"
    region = "eu-west-2"
  }
}

# remote backend from previous layer
data "terraform_remote_state" "pipelines" {
  backend = "s3"  # or other backend used to store state
  config = {
    bucket = "tf.bayis.co.uk"
    key = "state/embedding/02-lambdas.tfstate"
    region = "eu-west-2"
  }
}
