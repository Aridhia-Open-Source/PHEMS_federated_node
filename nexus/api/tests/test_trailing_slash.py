"""A trailing slash reaches the same route as the path without one, with no redirect."""


def test_trailing_slash_reaches_the_handler_without_a_redirect(client, admin_headers):
    for path in ("/projects", "/projects/"):
        response = client.get(path, headers=admin_headers, follow_redirects=False)
        assert response.status_code == 200, path

    response = client.post("/projects/", json={"name": "Slashed"}, headers=admin_headers, follow_redirects=False)
    assert response.status_code == 201
