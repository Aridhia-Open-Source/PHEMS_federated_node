import pytest
from app.helpers.errors import BadRequest
from app.helpers.validation import validate_mirror

BODY = {
    'upstream_uri': 'https://github.com/org/repo', 'secret_namespace': 'ns', 'secret_key': 'token',
    'gitea_owner': 'org', 'gitea_repo': 'repo', 'base_branch': 'main',
}


def post(client, auth, **over):
    return client.post('/mirrors', json={**BODY, **over}, headers=auth)


@pytest.mark.parametrize('uri', [
    'https://evil.example/o/r',
    'https://user:pw@github.com/o/r',
    'https://user@github.com/o/r',
    'https://github.com:444/o/r',
    'https://github.com:443/o/r',
    'http://github.com/o/r',
    'https://github.com.evil.example/o/r',
    'https://evil.example/github.com/o/r',
    'https://GITHUB.com/o/r',
    'https://127.0.0.1/o/r',
    'https://169.254.169.254/o/r',
    'https://kubernetes.default.svc/o/r',
    'https://localhost/o/r',
    'https://github.com/o/r?x=1',
    'https://github.com/o/r#frag',
    'https://github.com/o',
    'https://github.com/o/r/extra',
    'https://github.com/o/r/',
    'https://github.com//r',
    'https://github.com/../r',
    'https://github.com/o/..',
    'https://github.com/o/r r',
    'https://github.com/o/r\n',
    'https://github.com/o/r%2F..',
    'file:///etc/passwd',
    'git@github.com:o/r.git',
])
def test_upstream_uri_rejected(client, auth, uri):
    assert post(client, auth, upstream_uri=uri).status_code == 400


@pytest.mark.parametrize('uri', [
    'https://github.com/o/r', 'https://github.com/My-Org/my_repo.js', 'https://github.com/o/r.git',
])
def test_upstream_uri_accepted(client, auth, uri):
    assert post(client, auth, upstream_uri=uri, gitea_repo='x' + str(abs(hash(uri)))).status_code == 201


def test_patch_upstream_uri_rejected(client, auth):
    mid = post(client, auth).get_json()['id']
    for uri in ('https://evil.example/o/r', 'https://u:p@github.com/o/r'):
        assert client.patch(f'/mirrors/{mid}', json={'upstream_uri': uri}, headers=auth).status_code == 400


BAD = {
    'gitea_owner': ['../admin', '../admin/users', 'a/b', 'a:b', 'a b', 'a\tb', 'a\nb', 'a\x00b', '..', '.',
                    '-lead', 'x' * 101, 'a?b', 'a#b', 'a%2Fb', 'a\\b', 'é'],
    'gitea_repo': ['../x', 'a/b', 'a:b', 'a b', 'a\x7fb', '..', '.', 'x' * 101, 'a..b', 'a?b'],
    'base_branch': ['a:b', 'a b', 'a..b', 'a\x00b', '/main', 'main/', 'a//b', 'a~b', 'a^b', 'a?b', 'a*b',
                    'a[b', 'a\\b', 'a@{b', '@', 'main.lock', 'a/.b', 'x.', '-x', 'x' * 201, 'a\tb',
                    'refs/heads/..'],
    'secret_namespace': ['../kube-system', 'a/b', 'a:b', 'a b', 'A', 'a_b', '-a', 'a-', 'x' * 64, 'a.b',
                         'a\nb'],
    'secret_key': ['x/../..', '../x', 'a/b', 'a:b', 'a b', 'A', '-a', 'a..b', 'x' * 254, 'a\nb', 'a_b'],
}


@pytest.mark.parametrize('field,value', [(f, v) for f, vs in BAD.items() for v in vs])
def test_field_rejected_on_create_and_patch(client, auth, field, value):
    assert post(client, auth, **{field: value}).status_code == 400
    mid = post(client, auth).get_json()['id']
    assert client.patch(f'/mirrors/{mid}', json={field: value}, headers=auth).status_code == 400
    assert client.get(f'/mirrors/{mid}', headers=auth).get_json()[field] == BODY[field]


@pytest.mark.parametrize('over', [
    {'gitea_owner': 'my-org_1.x'}, {'gitea_repo': 'repo.name-1_x'},
    {'base_branch': 'release/1.2-x'}, {'base_branch': 'feature/a.b'},
    {'secret_namespace': 'gitea-mirror'}, {'secret_key': 'github.token-1'},
])
def test_field_accepted(client, auth, over):
    assert post(client, auth, **over).status_code == 201


def test_non_string_still_rejected():
    with pytest.raises(BadRequest):
        validate_mirror({**BODY, 'base_branch': 5}, partial=False)
