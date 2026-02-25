
# TODO


```python
GH_OWNER = "Aridhia-Open-Source"
GH_REPO = "phems-sandbox"
GH_REPO_URI = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}"
REQUESTS_DIR = "mgmt/requests"
RESULTS_DIR = "mgmt/results"
```


## Initiate dagster run from github PR

### Steps
- Setup github token exchange and test api calls works to repo [x]
- Setup polling of github repo for new pull requests [x]
- Skip pull requests if they do not include changes to the `REQUESTS_DIR` []
- Setup check for main branch polling to find changed files in task dir and extract json []
- Setup dagster sensor for polling the github repo and detecting merges []
- Setup sensor to yield a job run from the sensor with the parameters provided in the merged changes []

## Upload dagster results to github upon dagster-pipes job completion

### Steps
- Setup code for creating a zip of the shared mount directory for the run_id []
- Setup code for creating a new branch and opening a github pull request with the zipped results []
- Setup a dagster sensor which detects successful run events for dagster-pipes jobs []
- Setup a dagster sensor which detects failed run events for dagster-pipes jobs []
- Setup the dagster success sensor so that it uploads the zipped results as a new pr []
- Setup the dagster failure sensor so that it adds a comment to the original PR with the error as comment []
- We should always add a comment to the PR when the dagster run status changes or when it completes (TBC)

---

# Proof of concept

Use local scripts and file cursor to test conceptual functionality with base case

1) Detect new pull requests from the target repo
2) Filter pull requests that have existed before startup or already processed
3) Filter pull requests where there are no changes to the run requests dir
4) Parse JSON file requests from dir and print them out (will be api calls later)

---

1) Zip up the contents of a specified directory (small json files)
2) Create a new results branch with zip commited and push it to target repo
3) Open a new pull request using the new results branch

---

1) add a comment to a PR with a comment describing the jobs state


# Demo MVP
