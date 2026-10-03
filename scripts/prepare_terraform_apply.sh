# Must be SOURCED, not executed -- see below for why.
#
# Prepares the *current* shell for a `terraform plan`/`apply`: sources
# terraform/backend.env, exports TF_VAR_aws_region, cd's into terraform/, and
# runs `terraform init` with the matching -backend-config flags. Deliberately
# does NOT run plan/apply itself -- an infrastructure change stays a
# deliberate, manually-reviewed, manually-confirmed step (see README's
# "Deployment naar AWS"); this only removes the repetitive setup that has to
# precede it in every fresh shell.
#
# A child process can never `cd` or `export` into the shell that started it --
# the same reason scripts/bootstrap_local_infra.py has to be run as
# `eval "$(...)"`. Sourcing is the idiomatic bash-to-bash equivalent of that
# trick: it runs this script's commands directly in your shell instead of a
# child process, so the `cd`/`export` below actually stick around afterward.
#
# Usage: source scripts/prepare_terraform_apply.sh

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  echo "error: this script must be sourced, not executed." >&2
  echo "Run:   source scripts/prepare_terraform_apply.sh" >&2
  exit 1
fi

_prepare_terraform_apply() {
  local script_dir repo_root config_file

  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  repo_root="$(cd "$script_dir/.." && pwd)"
  config_file="$repo_root/terraform/backend.env"

  if [ ! -f "$config_file" ]; then
    echo "error: $config_file not found." >&2
    echo "Copy terraform/backend.env.example to terraform/backend.env and fill in" >&2
    echo "real values first (see README's \"Deployment naar AWS\")." >&2
    return 1
  fi

  # shellcheck disable=SC1090
  source "$config_file"
  export TF_VAR_aws_region="$AWS_REGION"

  cd "$repo_root/terraform" || return 1

  terraform init \
    -backend-config="bucket=$TF_STATE_BUCKET" \
    -backend-config="key=$TF_STATE_KEY" \
    -backend-config="region=$AWS_REGION" \
    -backend-config="dynamodb_table=$TF_STATE_LOCK_TABLE" || return 1

  echo
  echo "==> Ready: you're in terraform/, with TF_VAR_aws_region=$AWS_REGION exported."
  echo "==> Run 'terraform plan' or 'terraform apply' next."
}

_prepare_terraform_apply
_prepare_terraform_apply_status=$?
unset -f _prepare_terraform_apply
return "$_prepare_terraform_apply_status" 2>/dev/null || exit "$_prepare_terraform_apply_status"
unset _prepare_terraform_apply_status
