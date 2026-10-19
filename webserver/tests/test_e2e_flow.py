def test_full_flow(client, admin_headers, k8s_client, disabled_project, make_pr_batch, spec_raw):
    pid = disabled_project.id  # a new project is disabled

    def call(method, url, status, **kwargs):
        r = getattr(client, method)(url, headers=admin_headers, **kwargs)
        assert r.status_code == status, (url, r.json)
        return r.json

    creds = {"label": "e2e-creds", "provider": "K8S", "values": {"TOKEN": "t", "USERNAME": "u", "PASSWORD": "p"}}
    # 1-4. Global secret, git provider, trigger repository, results repository, dataset
    call("post", "/global/secrets", 201, json=creds)
    provider = call("post", "/global/providers", 201, json={
        "name": "github", "type": "github", "uri": "https://github.com", "api_uri": "https://api.github.com"
    })["id"]
    repo = {"provider_id": provider, "secret_label": "e2e-creds"}
    T = call("post", "/global/repositories/triggers", 201, json={"repo_path": "org/e2e-triggers", **repo})["id"]
    R = call("post", "/global/repositories/results", 201, json={"repo_path": "org/e2e-results", **repo})["id"]
    D = call("post", "/global/datasets", 201,
             json={"name": "E2eDs", "host": "db", "port": 5432, "secret_label": "e2e-creds"})["id"]

    # 5-7. Link secret, dataset and trigger repository (the project is still disabled)
    call("put", f"/projects/{pid}/secrets/e2e-creds", 201, json={})
    call("put", f"/projects/{pid}/datasets/{D}", 201, json={})
    call("put", f"/projects/{pid}/repositories/triggers/{T}", 201, json={"watch_dir": "triggers"})

    # 8. Link the results repository (the project must still be disabled)
    call("put", f"/projects/{pid}/repositories/results/{R}", 201, json={"target_dir": "results"})

    # 9-10. Enable the project
    body = call("patch", f"/projects/{pid}", 200, json={"enabled": True})
    assert body["enabled"] is True, body

    # 11. Pollable trigger repositories
    assert [i["id"] for i in call("get", "/global/repositories/triggers?pollable=true", 200)] == [T]

    # 12. Ingest pull requests: 1 and 2 match, 3 targets another branch (no trigger)
    batch = make_pr_batch(1, 2)
    batch["pull_requests"] += make_pr_batch(3, base_branch="dev")["pull_requests"]
    assert call("post", f"/global/repositories/triggers/{T}/pull_requests", 201, json=batch)["created"] == [1, 2, 3]

    # 13. Project sees the states of the ingested pull requests
    body = call("get", f"/projects/{pid}/repositories/triggers/{T}/pull_requests", 200)
    assert body["total"] == 2 and {i["number"]: i["state"] for i in body["items"]} == {1: "UNKNOWN", 2: "UNKNOWN"}

    # 14-15. Create a task from pull request 1; it succeeds
    task = call("post", f"/projects/{pid}/repositories/triggers/{T}/pull_requests/1/task", 201, json={"spec_raw": spec_raw})
    assert task["spec"]["dataset_id"] == D
    tid = task["id"]
    call("patch", f"/projects/{pid}/tasks/{tid}", 200, json={"status": "SUCCESS"})

    # 16-17. Post a result for the task; it is delivered as an opened pull request
    rid = call("post", f"/projects/{pid}/results", 201, json={"task_id": tid, "results_repository_id": R})["id"]
    body = call("patch", f"/projects/{pid}/results/{rid}", 200, json={
        "step": "OPENED", "state": "DELIVERED", "number": 7, "url": "https://github.com/org/e2e-results/pull/7"})
    assert (body["step"], body["state"]) == ("OPENED", "DELIVERED")

    # 18-19. Results of the task; project results filtered by step
    body = call("get", f"/projects/{pid}/tasks/{tid}/results", 200)
    assert len(body) == 1 and body[0]["results_repository_id"] == R
    assert len(call("get", f"/projects/{pid}/results?step=OPENED", 200)) == 1
