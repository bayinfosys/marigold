terraform {
  backend "s3" {
    bucket = "tf.bayis.co.uk"
    key    = "state/embedding/01-containers.tfstate"
    region = "eu-west-2"
  }
}

provider "aws" {
  region = "eu-west-2"
}
