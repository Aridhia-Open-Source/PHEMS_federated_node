import pytest
from app import create_app


@pytest.mark.parametrize('value', ['', ' ', '   '])
def test_empty_api_token_refuses_to_start(monkeypatch, value):
    monkeypatch.setenv('GITEA_MIRROR_API_TOKEN', value)
    with pytest.raises(RuntimeError):
        create_app()


def test_check_bearer_token_rejects_when_expected_empty(client):
    from flask import request
    from app.helpers.auth import check_bearer_token
    from app.helpers.errors import Unauthorized
    with client.application.test_request_context('/mirrors', headers={'Authorization': 'Bearer '}):
        with pytest.raises(Unauthorized):
            check_bearer_token('')


@pytest.mark.parametrize('header', [
    'Bearer ', 'Bearer', 'Bearer  test-token', 'bearer test-token', 'Basic test-token', 'test-token',
    'Bearer test-tokén', 'Bearer éé', 'Bearer 中', 'Bearer test-token ',
])
def test_bad_headers_are_401(client, header):
    resp = client.get('/mirrors', headers={'Authorization': header.encode('utf-8').decode('latin-1')})
    assert resp.status_code == 401


def test_non_ascii_raw_wsgi_header_is_401(client):
    resp = client.get('/mirrors', environ_overrides={'HTTP_AUTHORIZATION': 'Bearer tést'})
    assert resp.status_code == 401


def test_valid_token_works(client, auth):
    assert client.get('/mirrors', headers=auth).status_code == 200


def concrete(rule):
    path = rule.rule
    for arg in rule.arguments:
        path = path.replace(f'<int:{arg}>', '1').replace(f'<{arg}>', '1')
    return path


def test_every_route_except_health_requires_token(client):
    rules = [r for r in client.application.url_map.iter_rules() if r.endpoint != 'static']
    assert len(rules) > 10
    seen_health = False
    for rule in rules:
        if rule.endpoint == 'main.health':
            seen_health = True
            continue
        for method in rule.methods - {'HEAD', 'OPTIONS'}:
            path = concrete(rule)
            for headers in ({}, {'Authorization': 'Bearer wrong'}, {'Authorization': 'Bearer '}):
                resp = client.open(path, method=method, headers=headers)
                assert resp.status_code == 401, (method, path, headers)
    assert seen_health


def test_unknown_route_requires_token(client):
    assert client.get('/nope').status_code == 401
