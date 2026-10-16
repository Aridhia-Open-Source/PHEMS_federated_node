def test_link_global_trigger_repo_and_get_it_back(client, admin_headers, project, global_trigger_repo):
    url = f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}"

    put = client.put(url, json={"watch_dir": "triggers"}, headers=admin_headers)
    assert put.status_code == 201

    response = client.get(url, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["watch_dir"] == "triggers"
    assert response.json == put.json
