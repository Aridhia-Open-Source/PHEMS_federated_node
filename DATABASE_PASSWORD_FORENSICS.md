# Deep Forensic Analysis: Backend Database Password Configuration

**Date:** 2026-07-28
**Analysis Scope:** PHEMS Federated Node Backend Database Password Configuration
**Threat Level:** CRITICAL - Multiple vulnerabilities found

---

## PHASE 1: CODE ANALYSIS - DATABASE CONNECTION

### Finding 1.1: CRITICAL - Password Not URL-Encoded in Connection String
**File:** `/webserver/app/helpers/const.py`
**Lines:** 22-23, 6-31

```python
def build_sql_uri(
    username=None,
    password=None,
    host=None,
    port=None,
    database=None,
    ssl=None
):
    params = {}
    params['username'] = username or os.environ['BACKEND_DB_USER']
    params['password'] = password or os.environ['BACKEND_DB_PASSWORD']
    params['host'] = host or os.environ['PGHOST']
    params['port'] = port or os.environ['PGPORT']
    params['database'] = database or os.environ['BACKEND_DB_NAME']
    params['ssl'] = ssl or os.environ.get('DB_SSL', '')

    template = "postgresql://{username}:{password}@{host}:{port}/{database}{ssl}"
    return template % params  # ❌ NO URL ENCODING
    # return template.format(
    #     username=params['username'],
    #     password=quote_plus(params['password']),  # ✓ CORRECT WAY (commented out)
    #     host=params['host'],
    #     port=params['port'],
    #     database=params['database'],
    #     ssl=os.environ.get('DB_SSL', '')
    # )
```

**Issue:** Uses `%` string formatting without URL encoding. Special characters in passwords are not escaped.

**Failure Scenario:**
- Password: `Pfja092A2£FAw` (from .dev.env line 21)
- Special character: `£` (pound sign)
- Current URI becomes: `postgresql://user:Pfja092A2£FAw@localhost:5432/db`
- PostgreSQL URI parser will fail because `£` is not valid in URI authority section
- Expected behavior: `£` should be encoded as `%C2%A3`
- Status: **ACTIVE IN .dev.env** - PGPASSWORD has `£` character

**Other Vulnerable Passwords:**
- Any password with: `&`, `?`, `#`, `@`, `=`, `%`, `+`, `:`, `/`, `!`, `'`, `"`, etc.

**Impact:** Database connections will fail for any account with special characters in password.

---

### Finding 1.2: HIGH - KeyError If Environment Variables Missing at Import Time
**File:** `/webserver/app/helpers/const.py`
**Lines:** 15-19

```python
params['username'] = username or os.environ['BACKEND_DB_USER']      # ❌ Direct dict access
params['password'] = password or os.environ['BACKEND_DB_PASSWORD']  # ❌ Direct dict access
params['host'] = host or os.environ['PGHOST']                      # ❌ Direct dict access
params['port'] = port or os.environ['PGPORT']                      # ❌ Direct dict access
params['database'] = database or os.environ['BACKEND_DB_NAME']      # ❌ Direct dict access
params['ssl'] = ssl or os.environ.get('DB_SSL', '')                # ✓ Correct - has default
```

**Issue:** Lines 15-19 use `os.environ['KEY']` (direct dict access) instead of `os.environ.get('KEY', default)`.
- Direct dict access raises `KeyError` if variable is not set
- No fallback or default value provided
- Missing environment variables: `BACKEND_DB_USER`, `BACKEND_DB_PASSWORD`, `PGHOST`, `PGPORT`, `BACKEND_DB_NAME`

**Failure Scenario:**
- Environment variable not set before module import
- When `build_sql_uri()` is called, KeyError is raised
- Application fails to start
- Stack trace will expose that the env var name was missing (information disclosure)

**When This Could Occur:**
1. Init container runs before env vars are set
2. App imports base_model.py at module load time (see Finding 2.2)
3. If Kubernetes doesn't properly set env vars, app will fail

**Code Path:**
1. Dockerfile line 33: `ENTRYPOINT ["waitress-serve", "--call", "app:create_app"]`
2. app/__init__.py line 18: `from app.helpers.base_model import build_sql_uri, db`
3. base_model.py line 12: `engine = create_engine(build_sql_uri())`  ← Module import time!
4. const.py lines 15-19: Direct dict access ← KeyError thrown here

---

### Finding 1.3: CRITICAL - Module Import Time Database Connection
**File:** `/webserver/app/helpers/base_model.py`
**Line:** 12

```python
from app.helpers.const import build_sql_uri

engine = create_engine(build_sql_uri())  # ❌ Called at module import time
Base = declarative_base()
db = SQLAlchemy(model_class=Base)
```

**Issue:** Engine is created at module import time, not at application runtime.

**Failure Scenario:**
- When app/__init__.py imports base_model.py, line 12 executes immediately
- This happens during Flask app initialization
- If `build_sql_uri()` fails (Finding 1.2), the entire app fails to start
- No opportunity to catch or handle the error gracefully

**Call Chain:**
1. Container starts
2. Python executes Dockerfile ENTRYPOINT
3. waitress-serve imports app module
4. app/__init__.py line 18 imports base_model
5. base_model.py line 12 executes → creates database engine
6. If fails, entire app fails with no graceful degradation

---

### Finding 1.4: MEDIUM - Duplicate environment variable caching
**File:** `/webserver/app/helpers/const.py`
**Lines:** 34 and 63

```python
PUBLIC_URL = os.getenv("PUBLIC_URL")  # Line 34
...
PUBLIC_URL = os.getenv("PUBLIC_URL")  # Line 63 - DUPLICATE
```

**Issue:** `PUBLIC_URL` is defined twice at module level, creating unnecessary module-level variable caching.

**Impact:** Not a security issue, but demonstrates module-level environment variable reading that happens at import time. Any change to PUBLIC_URL at runtime won't be reflected.

---

## PHASE 2: DEPLOYMENT ANALYSIS - ENVIRONMENT VARIABLE INJECTION

### Finding 2.1: CORRECT - Backend container env var injection (db-migrations init)
**File:** `/k8s/federated-node/templates/backend-deployment.yaml`
**Lines:** 70-89

```yaml
- name: db-migrations
  image: {{ template "backend-image" . }}
  command: ["/bin/sh"]
  workingDir: /webserver
  {{- include "nonRootSC" . | nindent 10 }}
  args:
    [
      '-c',
      'python -m alembic upgrade head'
    ]
  envFrom:
    - configMapRef:
        name: backend-configmap  # Loads: PGHOST, BACKEND_DB_NAME, BACKEND_DB_USER, etc.
  imagePullPolicy: {{ .Values.pullPolicy }}
  env:
  - name: BACKEND_DB_PASSWORD  # ✓ Set from secret AFTER envFrom
    valueFrom:
      secretKeyRef:
        name: {{ .Values.backend.db.secret.name }}  # = "backend-db"
        key: {{ .Values.backend.db.secret.key }}     # = "password"
```

**Status:** ✓ CORRECT - Env vars properly injected via configmap + secret

---

### Finding 2.2: CORRECT - Backend main container env var injection
**File:** `/k8s/federated-node/templates/backend-deployment.yaml`
**Lines:** 100-141

```yaml
containers:
  - image: {{ template "backend-image" . }}
    name: backend
    ...
    envFrom:
      - configMapRef:
          name: backend-configmap
      - configMapRef:
          name: keycloak-config
      - secretRef:
          name: kc-secrets
    env:
    - name: BACKEND_DB_PASSWORD  # ✓ Set from secret
      valueFrom:
        secretKeyRef:
          name: {{ .Values.backend.db.secret.name }}    # = "backend-db"
          key: {{ .Values.backend.db.secret.key }}       # = "password"
```

**Status:** ✓ CORRECT - Both envFrom and env sections merge properly

---

### Finding 2.3: MEDIUM - Missing BACKEND_DB_PASSWORD in envFrom
**File:** `/k8s/federated-node/templates/backend-configmap.yaml`
**Lines:** 1-62

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: backend-configmap
  namespace: {{ .Release.Namespace }}
data:
  FLASK_APP: "/app"
  PGHOST: {{ .Values.db.host | quote }}
  PGPORT: {{ .Values.db.port | quote }}
  BACKEND_DB_NAME: {{ .Values.backend.db.name | quote }}
  BACKEND_DB_USER: {{ .Values.backend.db.user | quote }}
  # ... many more vars ...
  # ❌ BACKEND_DB_PASSWORD NOT HERE
```

**Analysis:** BACKEND_DB_PASSWORD is correctly NOT in the configmap.
- ConfigMaps are not encrypted, only base64 encoded
- Secrets are the correct location for passwords
- However, this is actually CORRECT behavior

**Status:** ✓ CORRECT - Passwords belong in Secrets, not ConfigMaps

---

### Finding 2.4: CORRECT - Secret creation and naming consistency
**File:** `/scripts/deploy.sh`
**Lines:** 65-67

```bash
kubectl create secret generic backend-db \
  --from-literal=password="$BACKEND_DB_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f - -n "$NAMESPACE"
```

**Verification:**
- Secret name: `backend-db` ✓
- Secret key: `password` ✓
- Value source: `BACKEND_DB_PASSWORD` ✓

**Matches in values.yaml:**
- values.yaml line 17: `name: backend-db` ✓
- values.yaml line 18: `key: password` ✓

**Status:** ✓ CORRECT - Secret name and key match across all files

---

## PHASE 3: CRITICAL - SQL INJECTION VULNERABILITY IN DATABASE INITIALIZATION

### Finding 3.1: CRITICAL - SQL Injection via Unescaped Password in backend-db-init.yaml
**File:** `/k8s/federated-node/templates/backend-db-init.yaml`
**Lines:** 31-51

```yaml
command:
  - sh
  - -c
  - |
    psql -h {{ .Values.db.host }} -U postgres -d postgres << 'SQL'
    CREATE DATABASE {{ include "backendDbName" . }};
    CREATE USER {{ .Values.backend.db.user }} WITH PASSWORD '${BACKEND_DB_PASSWORD}';
    ALTER DATABASE {{ include "backendDbName" . }} OWNER TO {{ .Values.backend.db.user }};
    GRANT ALL PRIVILEGES ON DATABASE {{ include "backendDbName" . }} TO {{ .Values.backend.db.user }};
    SQL
env:
  - name: PGPASSWORD
    valueFrom:
      secretKeyRef:
        name: postgres-superuser
        key: password
  - name: BACKEND_DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: {{ .Values.backend.db.secret.name }}
        key: {{ .Values.backend.db.secret.key }}
```

**Issue:** Line 37 uses unescaped shell variable in SQL string.

**Failure Scenario 1: SQL Syntax Error**
- Password: `my'password`
- Expanded SQL: `CREATE USER backend_admin WITH PASSWORD 'my'password';`
- Result: **SYNTAX ERROR** - Unterminated string literal
- Error: `ERROR: syntax error at or near "password"`
- Database user creation FAILS
- Application cannot connect to database

**Failure Scenario 2: SQL Injection**
- Password: `x'; DROP TABLE users; --`
- Expanded SQL: `CREATE USER backend_admin WITH PASSWORD 'x'; DROP TABLE users; --';`
- Result: **SQL INJECTION** - Malicious SQL executes
- Though in this case user creation happens first, the injection still succeeds
- Any SQL after the password line executes as injected code

**Failure Scenario 3: Shell Variable Interpretation**
- Password: `$VAR_NAME` or `$(command)`
- Shell expands variables before passing to psql
- Unintended substitution occurs
- Example: Password `$USER` becomes current shell user name

**Real-world Example from .dev.env:**
- .dev.env line 21: `PGPASSWORD=Pfja092A2£FAw`
- This password has special character `£` which is different
- But if someone uses a password with `'`, it will break

**Status:** ❌ ACTIVE VULNERABILITY - High probability of failure with certain passwords

---

### Finding 3.2: CRITICAL - SQL Injection in dagster-db-init.yaml
**File:** `/k8s/federated-node/templates/dagster-db-init.yaml`
**Line:** 38

```yaml
CREATE USER {{ .Values.fnDagster.db.user }} WITH PASSWORD '${DAGSTER_PG_PASSWORD}';
```

**Identical Issue:** Same SQL injection vulnerability as Finding 3.1

**Status:** ❌ ACTIVE VULNERABILITY

---

### Finding 3.3: CRITICAL - SQL Injection in keycloak-db-init.yaml
**File:** `/k8s/federated-node/templates/keycloak-db-init.yaml`
**Line:** 37

```yaml
CREATE USER {{ .Values.keycloak.db.user }} WITH PASSWORD '${KEYCLOAK_DB_PASSWORD}';
```

**Identical Issue:** Same SQL injection vulnerability as Finding 3.1

**Status:** ❌ ACTIVE VULNERABILITY

---

## PHASE 4: CONFIGURATION VALUE RESOLUTION

### Finding 4.1: VERIFY - Helm template variable resolution
**Values:**
- dev.values.yaml line 34: `name: backend-db`
- dev.values.yaml line 35: `key: password`
- values.yaml line 17: `name: backend-db`
- values.yaml line 18: `key: password`

**Template resolution in backend-deployment.yaml:**
- Line 88: `{{ .Values.backend.db.secret.name }}` → resolves to `"backend-db"` ✓
- Line 89: `{{ .Values.backend.db.secret.key }}` → resolves to `"password"` ✓

**Status:** ✓ CORRECT - Values properly resolve

---

## PHASE 5: POTENTIAL FAILURE MODES MATRIX

### Failure Mode Analysis

| # | Failure Mode | Severity | Status | Trigger |
|---|---|---|---|---|
| 1 | Password contains `£` (or other special chars) | CRITICAL | ACTIVE | PGPASSWORD in .dev.env has `£` |
| 2 | Password contains `'` (single quote) | CRITICAL | VULNERABLE | SQL injection in init scripts |
| 3 | Password contains `$` or backticks | CRITICAL | VULNERABLE | Shell expansion in init scripts |
| 4 | BACKEND_DB_PASSWORD not set at import time | HIGH | MITIGATED | Kubernetes sets vars before container starts |
| 5 | Secret not created in correct namespace | MEDIUM | MITIGATED | deploy.sh creates in correct namespace |
| 6 | Secret key name mismatch | LOW | CORRECT | Names verified to match |
| 7 | ConfigMap overrides Secret | LOW | CORRECT | env section overrides envFrom |
| 8 | Module-level env var caching | LOW | MITIGATED | Only affects module import, not runtime changes |

---

## SPECIFIC VULNERABILITY DETAILS

### Vulnerability #1: URL Encoding of Special Characters

**Technical Details:**
```
PostgreSQL URI Syntax: postgresql://[user[:password]@][netloc][:port][/dbname][?param=value]

Special characters that require URL encoding in the authority section:
- @ → %40 (used to separate credentials from netloc)
- : → %3A (used to separate user:password)
- # → %23 (fragment separator)
- ? → %3F (query separator)
- & → %26 (parameter separator)
- / → %2F (path separator)
- % → %25 (escape character itself)
- [ ] → %5B %5D (IPv6)
- Space → %20
- £ → %C2%A3 (UTF-8 encoded)
```

**Current Code Issues:**
- No URL encoding applied
- SQLAlchemy connection string parser may fail
- psycopg2 driver may fail
- Connection will be rejected with cryptic error

---

### Vulnerability #2: SQL Injection in CREATE USER Statements

**Technical Details:**
```sql
-- VULNERABLE CODE:
CREATE USER user WITH PASSWORD '${BACKEND_DB_PASSWORD}';

-- If password = my'password
-- Results in:
CREATE USER user WITH PASSWORD 'my'password';
-- SQL ERROR: unterminated string literal

-- If password = x'; DELETE FROM users; --
-- Results in:
CREATE USER user WITH PASSWORD 'x'; DELETE FROM users; --';
-- Multiple statements execute!

-- CORRECT ESCAPING IN POSTGRESQL:
-- Single quotes are escaped by doubling them
CREATE USER user WITH PASSWORD 'my''password';
-- OR use parameter binding (not available in heredoc)
```

---

## REMEDIATION RECOMMENDATIONS

### Critical: Fix 1 - URL Encode Password in build_sql_uri()
**File:** `/webserver/app/helpers/const.py`
**Change Lines:** 22-31

Replace:
```python
template = "postgresql://{username}:{password}@{host}:{port}/{database}{ssl}"
return template % params
```

With:
```python
return template.format(
    username=quote_plus(params['username']),
    password=quote_plus(params['password']),
    host=params['host'],
    port=params['port'],
    database=params['database'],
    ssl=params['ssl']
)
```

Required import: `from urllib.parse import quote_plus` (already exists on line 3)

---

### Critical: Fix 2 - Safe Database User Creation
**Files:**
- `/k8s/federated-node/templates/backend-db-init.yaml` (line 31-51)
- `/k8s/federated-node/templates/dagster-db-init.yaml` (line 31-51)
- `/k8s/federated-node/templates/keycloak-db-init.yaml` (line 31-51)

**Option A: Use pg_restore with SQL file** (Recommended)
```yaml
command:
  - sh
  - -c
  - |
    cat > /tmp/init.sql << 'SQLEOF'
    CREATE DATABASE {{ include "backendDbName" . }};
    CREATE USER {{ .Values.backend.db.user }} WITH PASSWORD '${BACKEND_DB_PASSWORD}' USING scram-sha-256;
    ALTER DATABASE {{ include "backendDbName" . }} OWNER TO {{ .Values.backend.db.user }};
    GRANT ALL PRIVILEGES ON DATABASE {{ include "backendDbName" . }} TO {{ .Values.backend.db.user }};
    SQLEOF
    psql -h {{ .Values.db.host }} -U postgres -d postgres -f /tmp/init.sql
```

**Option B: Use psql with -v parameter** (Requires escape handling)
```yaml
psql -h {{ .Values.db.host }} -U postgres -d postgres << 'SQL'
    CREATE DATABASE {{ include "backendDbName" . }};
    CREATE USER {{ .Values.backend.db.user }} WITH PASSWORD '''' || replace(:'pwd', '''', '''''') || '''' ;
    ALTER DATABASE {{ include "backendDbName" . }} OWNER TO {{ .Values.backend.db.user }};
    GRANT ALL PRIVILEGES ON DATABASE {{ include "backendDbName" . }} TO {{ .Values.backend.db.user }};
    SQL
```
Note: This is complex and error-prone.

---

### High: Fix 3 - Use os.environ.get() with Defaults
**File:** `/webserver/app/helpers/const.py`
**Lines:** 15-19

Replace:
```python
params['username'] = username or os.environ['BACKEND_DB_USER']
params['password'] = password or os.environ['BACKEND_DB_PASSWORD']
params['host'] = host or os.environ['PGHOST']
params['port'] = port or os.environ['PGPORT']
params['database'] = database or os.environ['BACKEND_DB_NAME']
```

With:
```python
params['username'] = username or os.environ.get('BACKEND_DB_USER', 'backend_admin')
params['password'] = password or os.environ.get('BACKEND_DB_PASSWORD', '')
params['host'] = host or os.environ.get('PGHOST', 'localhost')
params['port'] = port or os.environ.get('PGPORT', '5432')
params['database'] = database or os.environ.get('BACKEND_DB_NAME', 'backend')
```

Or better yet, require the env vars and fail early with a clear error:
```python
def _get_required_env(var_name):
    value = os.environ.get(var_name)
    if value is None:
        raise RuntimeError(f"Required environment variable {var_name} is not set")
    return value

params['username'] = username or _get_required_env('BACKEND_DB_USER')
params['password'] = password or _get_required_env('BACKEND_DB_PASSWORD')
# ... etc
```

---

### Medium: Fix 4 - Remove Duplicate module variable
**File:** `/webserver/app/helpers/const.py`
**Line:** 63

Remove duplicate definition of `PUBLIC_URL`.

---

## TESTING RECOMMENDATIONS

### Test 1: Special Characters in Password
```bash
# Set password with special characters and test connection
export BACKEND_DB_PASSWORD="pass@word#123"
python3 -c "from app.helpers.const import build_sql_uri; print(build_sql_uri())"
```

### Test 2: SQL Injection Attempt
```bash
# Create database user with password containing quote
export BACKEND_DB_PASSWORD="x'; DELETE FROM pg_database WHERE datname='test'--"
kubectl apply -f backend-db-init.yaml
```

### Test 3: Connection String Validation
```bash
# Verify the URI is properly formatted
python3 << 'PYTHON'
from urllib.parse import urlparse
from app.helpers.const import build_sql_uri
uri = build_sql_uri()
parsed = urlparse(uri)
print(f"Host: {parsed.hostname}")
print(f"User: {parsed.username}")
print(f"Password: {parsed.password}")
PYTHON
```

---

## SUMMARY

- **Critical Issues Found:** 3
  1. Unencoded special characters in URI
  2. SQL injection in all 3 database init scripts
  3. Module import time database connection attempt

- **High Issues Found:** 1
  1. KeyError if env vars missing (partial mitigation via Kubernetes)

- **Medium Issues Found:** 2
  1. Init time env var caching
  2. Unnecessary duplicate module variable

- **Recommendation:** Address Critical issues before production deployment

---

**Analysis Complete**
