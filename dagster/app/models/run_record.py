from pydantic import BaseModel, ConfigDict, Field


class RunNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The node (hospital) that ran the task, the chart's nodeId")


class RunProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(description="nexus-api's id of the task's project")
    name: str = Field(description="The project's name")


class RunTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_uri: str = Field(description="The trigger repository the pull request was merged in")
    pr_number: int = Field(description="The merged pull request's number")
    merge_commit_sha: str = Field(description="The pull request's merge commit, whose spec file the task ran")


class RunTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(description="nexus-api's id of the task")
    name: str = Field(description="The task's name")
    executor_id: str = Field(description="The Dagster run id that ran the task")
    dataset: str | None = Field(description="The dataset the task ran against, null when it used none")


class RunResults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zip_size_bytes: int = Field(description="The size of results.zip")
    file_count: int = Field(description="How many files results.zip holds")
    delivered_at: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        description="When the results were pushed, in UTC (YYYY-MM-DDTHH:MM:SSZ)",
    )


class RunRecord(BaseModel):
    """
    run.json: the node's record of one task run, delivered next to results.zip and spec.json
    in the results repository.
    """
    model_config = ConfigDict(extra="forbid")

    node: RunNode
    project: RunProject
    trigger: RunTrigger
    task: RunTask
    results: RunResults
