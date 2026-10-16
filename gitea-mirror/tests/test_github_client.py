import json
from pathlib import Path

import pytest
import requests
import responses

from app import github
from app.github import GithubRestClient, RateLimited, TokenExpired

FIXTURES = Path(__file__).parent / 'fixtures' / 'github'
API = 'https://api.github.com/repos/org/repo'
URI = 'https://github.com/org/repo.git'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setattr(github, 'read_secret_token', lambda ns, key: 'ghp_test')


@pytest.fixture
def client():
    return GithubRestClient()


def merged(client, cursor='2026-02-15T00:00:00Z'):
    return client.list_merged_pulls(URI, 'ns', 'key', 'main', cursor)


@responses.activate
def test_merged_pulls_paginate_and_stop_at_cursor(client):
    responses.get(f'{API}/pulls', json=fixture('pulls_page1.json'),
                  headers={'Link': f'<{API}/pulls?page=2>; rel="next"'})
    responses.get(f'{API}/pulls?page=2', json=fixture('pulls_page2.json'))

    result = merged(client)

    # PR 4 is closed unmerged, PR 1 is older than the cursor; oldest first
    assert [p['number'] for p in result] == [2, 3, 5]
    assert result[0] == {
        'number': 2, 'title': 'PR 2', 'author': 'user2', 'merged_at': '2026-03-01T00:00:00Z',
        'updated_at': '2026-03-01T00:00:00Z', 'merge_commit_sha': 'm2', 'head_sha': 'h2',
    }
    first = responses.calls[0].request
    assert 'state=closed' in first.url and 'base=main' in first.url and 'sort=updated' in first.url
    assert first.headers['Authorization'] == 'Bearer ghp_test'


@responses.activate
def test_cursor_stop_skips_later_pages(client):
    responses.get(f'{API}/pulls', json=fixture('pulls_page1.json'),
                  headers={'Link': f'<{API}/pulls?page=2>; rel="next"'})
    assert [p['number'] for p in merged(client, '2026-03-04T12:00:00Z')] == [5]
    assert len(responses.calls) == 1


@responses.activate
def test_etag_304_reuses_cached_page(client):
    responses.get(f'{API}/pulls', json=fixture('pulls_page2.json'), headers={'ETag': '"abc"'})
    first = merged(client)
    responses.replace(responses.GET, f'{API}/pulls', status=304)
    second = merged(client)

    assert first == second and len(first) == 2
    assert responses.calls[1].request.headers['If-None-Match'] == '"abc"'


@responses.activate
def test_list_users_merges_contributors_and_collaborators(client):
    responses.get(f'{API}/contributors', json=fixture('contributors.json'))
    responses.get(f'{API}/collaborators', json=fixture('collaborators.json'))
    assert client.list_users(URI, 'ns', 'key') == ['alice', 'bob', 'carol']


@responses.activate
def test_list_users_without_push_access_uses_contributors(client):
    responses.get(f'{API}/contributors', json=fixture('contributors.json'))
    responses.get(f'{API}/collaborators', status=403, json={'message': 'Must have push access'})
    assert client.list_users(URI, 'ns', 'key') == ['alice', 'bob']


@responses.activate
def test_rate_limit_raises_with_reset_time(client):
    responses.get(f'{API}/contributors', status=403, json={'message': 'rate limit'},
                  headers={'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1800000000'})
    with pytest.raises(RateLimited) as err:
        client.list_users(URI, 'ns', 'key')
    assert err.value.reset_at.timestamp() == 1800000000
    assert '2027-01-15' in str(err.value)


@responses.activate
def test_rate_limit_429_retry_after(client):
    responses.get(f'{API}/contributors', status=429, headers={'Retry-After': '60'})
    with pytest.raises(RateLimited):
        client.list_users(URI, 'ns', 'key')


@responses.activate
def test_401_is_token_expired(client):
    responses.get(f'{API}/contributors', status=401, json={'message': 'Bad credentials'})
    with pytest.raises(TokenExpired, match='token_expired'):
        client.list_users(URI, 'ns', 'key')


@responses.activate
def test_other_403_is_not_swallowed_on_pulls(client):
    responses.get(f'{API}/pulls', status=403, json={'message': 'forbidden'})
    with pytest.raises(requests.HTTPError):
        merged(client)
