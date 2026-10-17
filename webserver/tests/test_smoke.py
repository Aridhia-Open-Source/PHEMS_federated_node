def test_link_global_trigger_repo_and_get_it_back(client, admin_headers, project, global_trigger_repo):
    url = f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}"

    put = client.put(url, json={"watch_dir": "triggers"}, headers=admin_headers)
    assert put.status_code == 201

    response = client.get(url, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["watch_dir"] == "triggers"
    assert response.json == put.json


def test_admin_routes_live_under_global(client):
    rules = {rule.rule for rule in client.application.url_map.iter_rules()}
    assert {"/global/users/", "/global/users/reset-password", "/global/registries/"} <= rules
    assert not {rule for rule in rules if rule.split("/")[1] in ("users", "registries", "whitelisted_images")}


def test_reset_password_needs_no_token(client):
    response = client.put("/global/users/reset-password", json={})
    assert response.status_code not in (401, 404)
