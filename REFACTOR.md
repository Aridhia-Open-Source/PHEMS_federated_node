# MutliRepo Refactor

# owner: "your-org"
# repo: "your-repo"
# default_branch_override: "main" (currently hardcoded and to be moved to an api request)
# watchDir: "mgmt/requests"
# resultsDir: "mgmt/results"
# githubToken: K8sSecretValue

# TO DO: make configuration naming consistent (request/delivery scoping)

# RequestRepo
## Github repo for triggering experiment runs (i.e PHDS/mvp-code)

### Required Config
# owner: "your-org"
# repo: "your-repo"
# watchDir: "mgmt/requests" (could be hardcoded or a default?)
# githubToken: K8sSecretValue
# baseBranch - (to be found using github api - https://docs.github.com/en/rest/repos/repos?apiVersion=2026-03-10)
# default_branch_override - overrides default baseBranch if provided


# DeliveryRepo
## Github repo for delivering a requested experiment runs results to the client

### Required Config
# owner: "your-org"
# repo: "your-repo"
# resultsDir: "mgmt/results" (could be hardcoded or a default?)
# githubToken: K8sSecretValue
# baseBranch - (to be found using github api - https://docs.github.com/en/rest/repos/repos?apiVersion=2026-03-10)
# default_branch_override - overrides default baseBranch if provided


request -> delivery
request -> delivery


request ->
request -> -> delivery
request ->







# Testing Plan

## Pytest
- github sensors -> unit tests
- K8sPipe -> heavily mocked unit tests -> optional but difficult (integration test )
- Github Client -> unit tests (mocking the github api responses)



# github_transfer refactor

- make commit identity configurable with defaults
git config user.name "phems-bot"
git config user.email "phem-federated-node@users.noreply.github.com"

- investigate converting main.sh to python if not too challenging and simplifies code
- investigate zip logic and see if it can be made more explicit using python
- optimize git repo pulls using --shallow and flags to ignore large files i.e zips?
