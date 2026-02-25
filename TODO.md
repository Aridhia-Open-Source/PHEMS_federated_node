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
- setup the dagster failure sensor so that it adds a comment to the original PR with the error as comment []



