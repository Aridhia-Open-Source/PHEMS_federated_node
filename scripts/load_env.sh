# shellcheck shell=bash
# Sourced from the repo root by cluster.sh, deploy.sh, reload_app.sh and teardown.sh: loads the
# env files in order, so what you wrote in .dev.env wins over what scripts/configure.sh
# generated in .generated.env (the Tiltfile and mise.toml load them in the same order).
if [ -f .generated.env ]; then
  # shellcheck source=/dev/null
  source .generated.env
fi
source .dev.env
