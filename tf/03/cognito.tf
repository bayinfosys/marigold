resource "aws_cognito_user_pool" "users" {
  name = join("-", [var.project_name, var.env, "users"])

  password_policy {
    temporary_password_validity_days = 7

    minimum_length    = 8
    require_lowercase = true
    require_numbers   = true
    require_uppercase = false
    require_symbols   = false
  }

  username_attributes = ["email"]
  auto_verified_attributes = ["email"]

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

#  email_configuration {
#    email_sending_account  = "DEVELOPER"
#    from_email_address = aws_ses_email_identity.support.email
#    reply_to_email_address = aws_ses_email_identity.support.email
#    source_arn = aws_ses_email_identity.support.arn
#  }

  # https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools-working-with-aws-lambda-triggers.html
#  lambda_config {
#    post_confirmation = aws_lambda_function.cognito_signup_handler.arn
#    post_authentication = aws_lambda_function.cognito_postauth_handler.arn
#    custom_message = aws_lambda_function.cognito_custom_message_handler.arn
#  }

  tags = var.project_tags
}
