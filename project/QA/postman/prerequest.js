// Collection-level pre-request script, injected by scripts/postman_collection.py.
// nexus-api takes the token POST /login returns (a Keycloak refresh token) as the bearer, so the
// script logs in with {{username}} and {{password}} when {{token}} is empty or about to expire.
const path = pm.request.url.getPath();
const token = pm.environment.get('token');

function expiresAt(jwt) {
  const part = jwt.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
  return JSON.parse(atob(part + '='.repeat((4 - part.length % 4) % 4))).exp;
}

if (path !== '/login' && (!token || expiresAt(token) - 30 < Date.now() / 1000)) {
  pm.sendRequest({
    url: pm.variables.get('baseUrl') + '/login',
    method: 'POST',
    body: {
      mode: 'urlencoded',
      urlencoded: [
        { key: 'username', value: pm.variables.get('username') },
        { key: 'password', value: pm.variables.get('password') },
      ],
    },
  }, (err, res) => {
    if (err || res.code !== 200) {
      throw new Error(`login to ${pm.variables.get('baseUrl')} failed: ${err || `${res.code} ${res.text()}`}`);
    }
    pm.environment.set('token', res.json().token);
  });
}
