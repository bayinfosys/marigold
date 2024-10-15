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
