#!/usr/bin/env bash
# One-time (idempotent) bootstrap of the Terraform remote state backend.
#
# Reads its configuration from terraform/backend.env, which is gitignored --
# copy terraform/backend.env.example to terraform/backend.env and fill in
# real values before running this.
#
# Safe to re-run: the S3 bucket and DynamoDB table are created only if they
# don't already exist. In particular, edwinbulter-terraform-state already
# holds Terraform state for other applications -- this script reuses it
# as-is (and never touches its existing settings) rather than creating a
# second bucket, and namespaces this app's state under its own key.
# terraform-locks is a single DynamoDB table shared across applications for
# state locking; it needs no per-application setup beyond existing, since
# Terraform's S3 backend derives each lock item's key from the state's own
# bucket+key path and creates/removes that item itself during init/plan/apply.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$REPO_ROOT/terraform/backend.env"
EXAMPLE_FILE="$REPO_ROOT/terraform/backend.env.example"

if ! command -v aws >/dev/null 2>&1; then
  echo "error: the AWS CLI ('aws') is not installed or not on PATH." >&2
  exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
  echo "error: $CONFIG_FILE not found." >&2
  echo "Copy $EXAMPLE_FILE to terraform/backend.env and fill in real values first." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"

missing=()
for var in APP_NAME AWS_REGION TF_STATE_BUCKET TF_STATE_KEY TF_STATE_LOCK_TABLE; do
  if [ -z "${!var:-}" ]; then
    missing+=("$var")
  fi
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "error: terraform/backend.env is missing a value for: ${missing[*]}" >&2
  echo "See $EXAMPLE_FILE for the required keys." >&2
  exit 1
fi

echo "== S3 state bucket: $TF_STATE_BUCKET =="
if aws s3api head-bucket --bucket "$TF_STATE_BUCKET" --region "$AWS_REGION" 2>/dev/null; then
  echo "Already exists -- reusing it as-is (this may be shared with other applications;"
  echo "its existing versioning/encryption/public-access settings are left untouched)."
else
  echo "Not found -- creating it..."
  if [ "$AWS_REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$TF_STATE_BUCKET" --region "$AWS_REGION"
  else
    aws s3api create-bucket --bucket "$TF_STATE_BUCKET" --region "$AWS_REGION" \
      --create-bucket-configuration LocationConstraint="$AWS_REGION"
  fi
  aws s3api put-bucket-versioning --bucket "$TF_STATE_BUCKET" \
    --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption --bucket "$TF_STATE_BUCKET" \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-public-access-block --bucket "$TF_STATE_BUCKET" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  echo "Created, versioned, encrypted (SSE-S3), and blocked from public access."
fi

echo
echo "== DynamoDB lock table: $TF_STATE_LOCK_TABLE =="
if aws dynamodb describe-table --table-name "$TF_STATE_LOCK_TABLE" --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "Already exists -- reusing it (shared across applications)."
else
  echo "Not found -- creating it..."
  aws dynamodb create-table \
    --table-name "$TF_STATE_LOCK_TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$AWS_REGION" >/dev/null
  aws dynamodb wait table-exists --table-name "$TF_STATE_LOCK_TABLE" --region "$AWS_REGION"
  echo "Created."
fi

echo
echo "Locking for '$APP_NAME' needs no separate item or setup: Terraform's S3"
echo "backend derives each lock item's key (LockID) from the state's own"
echo "bucket+key path ('$TF_STATE_BUCKET/$TF_STATE_KEY'), so this shared table"
echo "already supports it -- Terraform creates and removes that item itself"
echo "during every init/plan/apply."

echo
echo "== Backend ready. Initialize and apply Terraform with: =="
cat <<EOF
cd terraform
export TF_VAR_aws_region="$AWS_REGION"
terraform init \\
  -backend-config="bucket=$TF_STATE_BUCKET" \\
  -backend-config="key=$TF_STATE_KEY" \\
  -backend-config="region=$AWS_REGION" \\
  -backend-config="dynamodb_table=$TF_STATE_LOCK_TABLE"
terraform apply
EOF
