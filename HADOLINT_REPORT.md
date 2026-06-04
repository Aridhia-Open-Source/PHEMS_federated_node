# Hadolint Report

Generated: 2026-06-04

## Summary

| Rule | Severity | Count | Description |
|------|----------|-------|-------------|
| DL3008 | Warning | 4 | Unversioned apt-get packages |
| DL3009 | Info    | 1 | apt lists not deleted after install |
| DL3013 | Warning | 1 | Unversioned pip package |
| DL3015 | Info    | 1 | `--no-install-recommends` missing |
| DL3042 | Warning | 2 | pip cache not disabled |
| DL3045 | Warning | 4 | COPY to relative path without WORKDIR |
| DL4006 | Warning | 1 | No `pipefail` before piped RUN |

**Total: 14 findings across 6 Dockerfiles**

---

## Findings by File

### `.gists/pipcompile/webserver/Dockerfile`

#### Line 21 — DL3045 `COPY` to a relative destination without `WORKDIR` set

```dockerfile
COPY requirements.txt .
```

**Explanation:** The destination `.` is relative to the current working directory inside the container. When no `WORKDIR` has been declared before this instruction, the working directory defaults to `/`, which is implicit and fragile. Docker best practice is to explicitly declare `WORKDIR` before any `COPY` that uses a relative path, so the destination is unambiguous and the image is easier to reason about.

**Fix:** Move `WORKDIR /` (currently at line 31) to before the first `COPY` instruction, or change the destination to an absolute path.

```dockerfile
WORKDIR /
COPY requirements.txt .
```

---

### `.gists/.models/julia/Dockerfile`

#### Line 26 — DL3042 Avoid use of pip cache directory

```dockerfile
RUN pip install dagster-pipes==1.11.10
```

**Explanation:** pip stores a local download cache in `~/.cache/pip` (or similar) inside the image layer. This cache is never used again during normal image usage, so it increases image size for no benefit.

**Fix:** Add `--no-cache-dir`:

```dockerfile
RUN pip install --no-cache-dir dagster-pipes==1.11.10
```

#### Line 29 — DL3045 `COPY` to a relative destination without `WORKDIR` set

```dockerfile
COPY entrypoint.py .
```

**Explanation:** The Python stage (which begins at `FROM python:3.12-slim`) does not set a `WORKDIR` before this `COPY`. The implicit destination is `/`, which is undesirable — files land in the filesystem root rather than a predictable application directory.

**Fix:** Add a `WORKDIR` declaration in the Python stage before the `COPY` instructions:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir dagster-pipes==1.11.10

COPY entrypoint.py .
```

---

### `.gists/.models/python/Dockerfile`

#### Line 3 — DL3013 Pin versions in pip

```dockerfile
RUN pip install dagster-pipes
```

**Explanation:** Installing a package without a version constraint means the image will pull whichever version is latest at build time. This makes builds non-reproducible — two builds from the same `Dockerfile` can produce different images if a new package version is released between them. A newer version could introduce breaking changes or incompatible dependencies.

**Fix:** Pin to a specific version:

```dockerfile
RUN pip install --no-cache-dir dagster-pipes==<version>
```

Run `pip index versions dagster-pipes` or check PyPI to find the current stable version.

#### Line 3 — DL3042 Avoid use of pip cache directory

```dockerfile
RUN pip install dagster-pipes
```

**Explanation:** Same as the Julia Dockerfile above — pip's download cache is baked into the layer and never reused, inflating the image unnecessarily.

**Fix:** Add `--no-cache-dir` (combine with the version-pinning fix above):

```dockerfile
RUN pip install --no-cache-dir dagster-pipes==<version>
```

#### Lines 5–6 — DL3045 `COPY` to a relative destination without `WORKDIR` set (×2)

```dockerfile
COPY entrypoint.py .
COPY main.py .
```

**Explanation:** No `WORKDIR` is set anywhere in this Dockerfile. Both files are copied to the implicit root `/`. As above, this is fragile and results in application files sitting at the filesystem root (`/entrypoint.py`, `/main.py`) rather than inside a clean, dedicated directory.

**Fix:** Add `WORKDIR /app` before the `COPY` instructions:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir dagster-pipes==<version>

COPY entrypoint.py .
COPY main.py .
```

---

### `.gists/demo-dbs/build/mssqsl-krb/Dockerfile`

#### Line 5 — DL3008 Pin versions in apt-get install

```dockerfile
RUN apt-get update \
    && apt-get install -y realmd adcli adutil krb5-user \
    ...
```

**Explanation:** Like unversioned pip installs, unversioned `apt-get install` makes the build non-reproducible. A rebuilt image could receive a newer version of any of these packages, potentially breaking Kerberos integration or introducing incompatible behaviour with the MSSQL server.

**Fix:** Pin each package to a specific version. Run `apt-cache policy <package>` on a Debian/Ubuntu host to find the available pinnable version strings:

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        realmd=<version> \
        adcli=<version> \
        adutil=<version> \
        krb5-user=<version> \
    && rm -rf /var/lib/apt/lists/*
```

#### Line 5 — DL3009 Delete apt lists after installing

```dockerfile
RUN apt-get update \
    && apt-get install -y realmd adcli adutil krb5-user \
    && /opt/mssql/bin/mssql-conf set network.kerberoskeytabfile /var/opt/mssql/secrets/mssql.keytab
```

**Explanation:** After `apt-get install`, the package index files in `/var/lib/apt/lists/` are left in the image layer. These files are only needed to resolve package names during installation and serve no purpose at runtime. Leaving them in adds unnecessary bulk to the image.

**Fix:** Chain a `rm -rf /var/lib/apt/lists/*` at the end of the same `RUN` layer. It must be in the same `RUN` to actually reduce the layer size:

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        realmd adcli adutil krb5-user \
    && /opt/mssql/bin/mssql-conf set network.kerberoskeytabfile /var/opt/mssql/secrets/mssql.keytab \
    && rm -rf /var/lib/apt/lists/*
```

#### Line 5 — DL3015 Specify `--no-install-recommends`

```dockerfile
apt-get install -y realmd adcli adutil krb5-user
```

**Explanation:** Without `--no-install-recommends`, apt will also install recommended (but not strictly required) packages for each of the listed packages. This can silently pull in many extra packages — documentation, locale data, optional tool dependencies — significantly enlarging the image without any benefit.

**Fix:** Add the flag (combine with the DL3008 and DL3009 fixes above):

```dockerfile
apt-get install -y --no-install-recommends realmd adcli adutil krb5-user
```

---

### `webserver/Dockerfile`

#### Line 10 — DL3008 Pin versions in apt-get install

```dockerfile
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        python3-dev \
        gcc \
        curl \
    && rm -rf /var/lib/apt/lists/*
```

**Explanation:** The same non-reproducibility concern as the other Dockerfiles. `libpq-dev`, `python3-dev`, `gcc`, and `curl` are all unversioned. A future rebuild could silently pick up a newer version of any of them.

**Fix:** Pin each package. The versions will depend on the base Debian version used by `python:3.13.5-slim`. Run `apt-cache policy <package>` inside a throwaway container (`docker run --rm python:3.13.5-slim apt-cache policy libpq-dev`) to determine the available version:

```dockerfile
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq-dev=<version> \
        python3-dev=<version> \
        gcc=<version> \
        curl=<version> \
    && rm -rf /var/lib/apt/lists/*
```

---

### `build/db-connector/Dockerfile`

#### Line 10 — DL3008 Pin versions in apt-get install

```dockerfile
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        odbcinst \
        unixodbc \
        libmariadb3 \
        libmariadb-dev \
        pkg-config \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*
```

**Explanation:** All eight packages are unversioned. The same reproducibility concern applies — a rebuild of this connector image at a later date could silently use newer versions of any ODBC or MariaDB library, potentially breaking database connectivity.

**Fix:** Pin each package. Run `apt-cache policy <package>` inside a throwaway `python:3.13.5-slim` container for exact version strings.

#### Line 23 — DL3008 Pin versions in apt-get install

```dockerfile
ACCEPT_EULA=Y apt-get install --no-install-recommends -y msodbcsql18
```

**Explanation:** `msodbcsql18` is the Microsoft ODBC Driver for SQL Server. Like the packages above, leaving it unversioned allows silent upgrades on rebuild. A major version bump of the MSSQL ODBC driver can change wire-protocol behaviour or TLS requirements.

**Fix:** Pin to a specific version of `msodbcsql18` from the Microsoft package feed.

#### Line 23 — DL4006 Set `SHELL` option `-o pipefail` before `RUN` with a pipe

```dockerfile
RUN DEBIAN_VERSION=$(grep VERSION_ID /etc/os-release | cut -d '"' -f 2) \
    && MSSQL_PROD_URL="..." \
    && curl -LsSf "${MSSQL_PROD_URL}" -o packages-microsoft-prod.deb \
    ...
```

**Explanation:** The subshell `$(grep ... | cut ...)` contains a pipe. By default, a shell pipeline's exit code is the exit code of the last command only — if `grep` fails but `cut` succeeds, the error is swallowed silently and `DEBIAN_VERSION` may be set to an empty string. Setting `pipefail` makes the entire pipeline fail if any component fails, so Docker catches the error rather than proceeding with a bad `DEBIAN_VERSION` value and producing a broken image.

**Fix:** Add `SHELL ["/bin/bash", "-o", "pipefail", "-c"]` before this `RUN` instruction (or once near the top of the file, before any piped `RUN`):

```dockerfile
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN DEBIAN_VERSION=$(grep VERSION_ID /etc/os-release | cut -d '"' -f 2) \
    ...
```

---

## Remediation Plan

Work through the files in this order (highest blast-radius first):

1. **`build/db-connector/Dockerfile`** (3 findings including DL4006 — active production connector image)
   - Add `SHELL ["/bin/bash", "-o", "pipefail", "-c"]` before the MSSQL install `RUN` block.
   - Pin all apt packages in both `RUN` blocks. Use `docker run --rm python:3.13.5-slim` to query exact versions.

2. **`webserver/Dockerfile`** (1 finding — active production webserver image)
   - Pin all apt packages in the install block.

3. **`.gists/demo-dbs/build/mssqsl-krb/Dockerfile`** (3 findings — demo/test image)
   - Add `--no-install-recommends`, pin package versions, and add `rm -rf /var/lib/apt/lists/*` to the `RUN` block.

4. **`.gists/.models/python/Dockerfile`** (3 findings — model template)
   - Add `WORKDIR /app`, pin `dagster-pipes` version, add `--no-cache-dir`.

5. **`.gists/.models/julia/Dockerfile`** (2 findings — model template)
   - Add `WORKDIR /app` in the Python stage, add `--no-cache-dir` to the pip install.

6. **`.gists/pipcompile/webserver/Dockerfile`** (1 finding — pip-compile helper image)
   - Move `WORKDIR /` to before the first `COPY` instruction.

> **Note on apt version pinning:** Version strings are Debian-release-specific. The safest approach is to query versions from inside a throwaway container matching the exact base image tag used in each Dockerfile, then commit the pinned values. Example:
> ```sh
> docker run --rm python:3.13.5-slim bash -c "apt-get update -qq && apt-cache policy libpq-dev gcc curl python3-dev"
> ```
