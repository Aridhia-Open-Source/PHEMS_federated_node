def test_full_flow(client, admin_headers, k8s_client, project, make_pr_batch, spec_raw):
    pid = project.id

    # 1. Global secret
    r = client.post("/global/secrets", json={
        "label": "e2e-creds", "provider": "K8S",
        "values": {"TOKEN": "t", "USERNAME": "u", "PASSWORD": "p"}
    }, headers=admin_headers)
    assert r.status_code == 201, r.json

    # 2. Global trigger repository
    r = client.post("/global/repositories/triggers", json={
        "uri": "github.com/org/e2e-triggers", "provider": "github", "secret_label": "e2e-creds"
    }, headers=admin_headers)
    assert r.status_code == 201, r.json
    T = r.json["id"]

    # 3. Global results repository
    r = client.post("/global/repositories/results", json={
        "uri": "github.com/org/e2e-results", "provider": "github", "secret_label": "e2e-creds"
    }, headers=admin_headers)
    assert r.status_code == 201, r.json
    R = r.json["id"]

    # 4. Global dataset
    r = client.post("/global/datasets", json={
        "name": "E2eDs", "host": "db", "port": 5432, "secret_label": "e2e-creds"
    }, headers=admin_headers)
    assert r.status_code == 201, r.json
    D = r.json["id"]

    # 5. Link the secret to the project
    r = client.put(f"/projects/{pid}/secrets/e2e-creds", json={}, headers=admin_headers)
    assert r.status_code == 201, r.json

    # 6. Link the dataset to the project
    r = client.put(f"/projects/{pid}/datasets/{D}", json={}, headers=admin_headers)
    assert r.status_code == 201, r.json

    # 7. Link the trigger repository (first link, no lock needed)
    r = client.put(f"/projects/{pid}/repositories/triggers/{T}", json={"watch_dir": "triggers"}, headers=admin_headers)
    assert r.status_code == 201, r.json

    # 8. Lock the project
    r = client.patch(f"/projects/{pid}", json={"locked": True}, headers=admin_headers)
    assert r.status_code == 200, r.json

    # 9. Link the results repository (needs the lock)
    r = client.put(f"/projects/{pid}/repositories/results/{R}", json={"target_dir": "results"}, headers=admin_headers)
    assert r.status_code == 201, r.json

    # 10. Enable and unlock the project
    r = client.patch(f"/projects/{pid}", json={"enabled": True, "locked": False}, headers=admin_headers)
    assert r.status_code == 200, r.json
    assert r.json["enabled"] is True, r.json
    assert r.json["locked"] is False, r.json

    # 11. Active trigger repositories
    r = client.get("/global/repositories/triggers?active_link=true", headers=admin_headers)
    assert r.status_code == 200, r.json
    assert [item["id"] for item in r.json] == [T], r.json

    # 12. Ingest pull requests: 1 and 2 match, 3 targets another branch
    batch = make_pr_batch(1, 2)
    batch["pull_requests"] += make_pr_batch(3, base_branch="dev")["pull_requests"]
    r = client.post(f"/global/repositories/triggers/{T}/pull_requests", json=batch, headers=admin_headers)
    assert r.status_code == 201, r.json
    assert r.json["created"] == [1, 2, 3], r.json

    # 13. Project sees the states of the ingested pull requests
    r = client.get(f"/projects/{pid}/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert r.status_code == 200, r.json
    assert r.json["total"] == 3, r.json
    states = {item["number"]: item["state"] for item in r.json["items"]}
    assert states == {1: "UNKNOWN", 2: "UNKNOWN", 3: "IGNORED"}, r.json

    # 14. Create a task from pull request 1
    r = client.post(f"/projects/{pid}/repositories/triggers/{T}/pull_requests/1/task",
                    json={"spec_raw": spec_raw}, headers=admin_headers)
    assert r.status_code == 201, r.json
    assert r.json["spec"]["dataset_id"] == D, r.json
    tid = r.json["id"]

    # 15. Task succeeds
    r = client.patch(f"/tasks/{tid}", json={"status": "SUCCESS"}, headers=admin_headers)
    assert r.status_code == 200, r.json

    # 16. Post a result for the task
    r = client.post(f"/projects/{pid}/results", json={"task_id": tid, "results_repository_id": R},
                    headers=admin_headers)
    assert r.status_code == 201, r.json
    rid = r.json["id"]

    # 17. Result delivered as an opened pull request
    r = client.patch(f"/projects/{pid}/results/{rid}", json={
        "step": "OPENED", "state": "DELIVERED", "number": 7,
        "url": "https://github.com/org/e2e-results/pull/7"
    }, headers=admin_headers)
    assert r.status_code == 200, r.json
    assert r.json["step"] == "OPENED", r.json
    assert r.json["state"] == "DELIVERED", r.json

    # 18. Results of the task
    r = client.get(f"/tasks/{tid}/results", headers=admin_headers)
    assert r.status_code == 200, r.json
    assert len(r.json) == 1, r.json
    assert r.json[0]["results_repository_id"] == R, r.json

    # 19. Project results filtered by step
    r = client.get(f"/projects/{pid}/results?step=OPENED", headers=admin_headers)
    assert r.status_code == 200, r.json
    assert len(r.json) == 1, r.json
