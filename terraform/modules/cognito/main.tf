# MFA is deliberately off: a stated PoC-scope simplification (see
# docs/owasp-top-10.md A07), not an oversight.
resource "aws_cognito_user_pool" "this" {
  name = var.user_pool_name

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "OFF"

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

# Confidential client (generate_secret = true): every Cognito call in this
# project happens server-side, in Lambda, via boto3 -- never from the
# browser -- so a kept client secret is the correct choice here, unlike the
# public-client pattern used for SPA/mobile apps.
resource "aws_cognito_user_pool_client" "this" {
  name         = var.app_client_name
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret = true

  # Both are off by default; without them InitiateAuth fails with an opaque
  # NotAuthorizedException that doesn't name the missing auth flow.
  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # So InitiateAuth/ForgotPassword never reveal whether an email is registered.
  prevent_user_existence_errors = "ENABLED"
}

# No "Customers" group exists: absence of group membership is the customer
# default. Matches "1 vaste administrator" -- one real group to manage, not two.
resource "aws_cognito_user_group" "admins" {
  name         = "Admins"
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Exclusive access to the admin backoffice."
}
