# 0044. Security scanning and version pinning

Status: Proposed, 2026-11-26.

## Context

- **Nothing scans the repository for security problems today.** CI runs pylint, hadolint, helm lint and the tests. A vulnerable base image, a leaked key, an unsafe workflow or an open storage account would merge unnoticed.
- **Versions are loose.** GitHub Actions are pinned to tags, base images to tags, and most CLI tools are "current stable". A tag can move. On 19 March 2026 an attacker force-pushed 76 of 77 version tags of `aquasecurity/trivy-action` to credential-stealing code and published a malicious Trivy release; images referenced by digest were not affected ([GHSA-69fq-xp46-6x23](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23)). A scanner that runs in our CI with our tokens is as exposed as anything else we install.
- **What needs scanning:**
  - container images: `nexus-api-fn`, `dagster-fn`, `nexus-ui-fn`, `nexus-operator-fn`, `keycloak-fn`, `kc-init-fn`, `alpine-fn`, and the `demo-fn` task image (names from `docker-bake.hcl`);
  - Python dependencies (`requirements*.txt`) and UI npm dependencies (`nexus/ui/package-lock.json`);
  - the Helm chart, Kubernetes manifests, Dockerfiles and the Flux configuration (`k8s/`, `build/`, the site repository files);
  - Pulumi programs (`pulumi/`, ADR 0034, [PR #773](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/773));
  - secrets in files and in git history;
  - our own Python code;
  - the GitHub workflows.
- **The repository is public and GPL-3.0.** Tools that run only in CI ship nothing and link nothing, so their licences do not touch ours. The tools should still be open source.
- **Scanners disagree.** Each finds things the others miss and raises findings the others call noise. Choosing needs data from this repository, not opinions.

## Decision

One rule for versions: **every version is locked to a hash, and one bot proposes the bumps.** One runner runs the scanners from one pinned container with one config, and starts report-only.

### Tools

| Area | Tool | Why over the alternative |
|---|---|---|
| Images, dependencies, config, secrets in files | Trivy | Over Grype: it also scans Helm, Kubernetes and Dockerfile config and finds secrets. Over pip-audit and `npm audit`: one tool and one report for Python and npm. |
| Chart, manifests, Dockerfiles, Flux | Trivy config | Over Checkov and KICS: good enough for Helm and Kubernetes, and no second tool to run. |
| Secrets in git history | Gitleaks | Over TruffleHog: faster, and it never sends a found key to the provider to "verify" it. |
| Our Python code, Pulumi Python | Semgrep | Over Bandit: several languages, custom rules, and the same tool covers Pulumi. |
| GitHub workflows | zizmor and actionlint | zizmor finds security problems (injection, over-broad permissions, unpinned actions); actionlint finds syntax and expression errors. Neither does the other's job. |
| Version bumps | Renovate | Over Dependabot version updates: it updates mise tools and Action commit pins and keeps the version comment. Dependabot security alerts stay on, since they cost nothing. |
| Action pins | pinact | Rewrites tags to full commit SHAs with a version comment, and checks that every Action is pinned. |

Grype, TruffleHog, Checkov, KICS, Bandit and OSV-Scanner run report-only in the first stage as comparison candidates. The rollout decides which stay; the table above is the expected winner for each area.

### Overlaps

- **Trivy and Gitleaks both find secrets.** Trivy's secret scanner reads current files; Gitleaks also walks history. Keep both for the first stage and compare; if Trivy's finds nothing Gitleaks does not, turn Trivy's off (`scanners: vuln,misconfig`).
- **Trivy and Semgrep both look at code-adjacent files** (Dockerfiles, YAML). Trivy owns configuration; Semgrep owns source.

### Pulumi

Trivy config and Checkov do not read Pulumi programs: they read rendered Terraform, CloudFormation and Kubernetes files, not Python that calls a provider. So:

- **Semgrep custom rules on the Pulumi Python** catch the known-bad settings (public blob access, an AKS cluster with no network policy, a Key Vault with purge protection off).
- **Pulumi CrossGuard policies** run on `pulumi preview` and check the planned resources. They arrive with the real Pulumi stack, not with this ADR.

### Runner

MegaLinter runs the tools from one container image with one config file (`.mega-linter.yml`), and writes SARIF that goes to GitHub code scanning (free for a public repository). Every finding lands in the Security tab and on the pull request, whichever tool made it.

The workflow pins the MegaLinter image by digest, not by tag: the Action's own `action.yml` points at a tag, so pinning only the Action commit would still pull a mutable image.

### Version pinning

- **GitHub Actions** are pinned to the full commit SHA with the version in a comment (`uses: actions/checkout@<sha> # v7.0.1`). `pinact run` rewrites them and `pinact run --check` fails CI on an unpinned one.
- **CLI tools** are declared in `mise.toml` and locked with the mise lockfile (`mise.lock`, which records checksums). CI installs them through mise, so CI and a developer's machine run the same versions.
- **Container images** (base images in Dockerfiles, the MegaLinter image, images in the chart values) are pinned by digest next to their tag.
- **Renovate** proposes the bump for every one of these, plus pip (`pip-compile` output) and npm, one pull request each, grouped by ecosystem.

### Licences

All open source, and none ships with the node.

| Tool | Licence |
|---|---|
| Trivy | Apache-2.0 |
| Gitleaks, Betterleaks | MIT |
| TruffleHog | AGPL-3.0 |
| Semgrep | LGPL-2.1 (the community rules are under the Semgrep Rules License) |
| zizmor, actionlint, pinact, mise | MIT |
| Checkov, KICS, Grype, OSV-Scanner, Bandit | Apache-2.0 |
| Renovate, MegaLinter | AGPL-3.0 |

AGPL tools only run in CI; we run them, we do not offer them as a service or distribute them, so the AGPL has nothing to attach to. Gitleaks' official GitHub Action needs a free licence key for organisation repositories, so CI runs the pinned binary instead. MegaLinter v10 replaced Gitleaks with Betterleaks (same author, reads `.gitleaks.toml`); the full history scan runs the Gitleaks binary in its own job, since a runner image rarely gets a full clone.

### Configuration

Scope, ignores and pass bars live in each tool's own file, one per tool. Every ignore carries a reason and an expiry date, so an ignore comes back for review instead of staying for good.

```yaml
# trivy.yaml: what to scan, and what to skip
scan:
  scanners: [vuln, misconfig, secret]
  skip-dirs: [node_modules, charts, .venv]
  skip-files: [nexus/api/openapi.json, nexus/ui/src/api/schema.d.ts]
severity: [CRITICAL, HIGH]
ignore-unfixed: true
```

```yaml
# .trivyignore.yaml: one entry per accepted finding, with a reason and an end date
vulnerabilities:
  - id: CVE-2026-0000
    paths: ["nexus/api/requirements.txt"]
    statement: "Not reachable: the vulnerable parser is never called (checked 2026-11-26)."
    expired_at: 2027-02-26
```

```toml
# .gitleaks.toml: allow a known test value, say why
[allowlist]
description = "Fixtures with fake credentials"
paths = ['''dagster/app/tests/.*''', '''nexus/api/tests/.*''']
```

```yaml
# .mega-linter.yml: scope for every tool in one place
FILTER_REGEX_EXCLUDE: '(node_modules/|charts/|nexus/ui/src/api/schema\.d\.ts|nexus/api/openapi\.json)'
```

**Pass bars**

| Tool | Stage 1 | Stage 2 (gate) |
|---|---|---|
| Trivy vulnerabilities, Grype, OSV-Scanner | report only | fail on CRITICAL and HIGH with a fix available |
| Trivy config | report only | fail on CRITICAL and HIGH |
| Secrets (Trivy, Gitleaks, TruffleHog) | report only | fail on any finding |
| Workflows (zizmor, actionlint) | report only | fail on any finding |
| Semgrep | report only | fail on `ERROR` severity; `WARNING` and `INFO` report only |
| Bandit, Checkov, KICS | report only | decided after the comparison |

### Rollout

1. **Report only.** MegaLinter runs every candidate with errors disabled and uploads SARIF. Nothing blocks a merge.
2. **Compare.** A job reads each tool's SARIF and writes a table to the job summary: findings seen by more than one tool, findings seen by only one, counts by severity, and run time per tool. The team reads the Security tab against it.
3. **Choose and gate.** Tools that add nothing are dropped. The survivors move to the pass bars above, one at a time, secrets and workflows first.
4. **Pin and bump.** Actions, tools and images are pinned in the same stack; Renovate is turned on once the pins exist.

## Consequences

- Security findings show up in the Security tab and on pull requests; a finding can be dismissed there with a reason.
- Every ignore has an owner's reason and an expiry; an expired ignore makes the finding visible again.
- Pinned versions mean a bump is always a reviewed pull request, never a surprise. The cost is the volume of Renovate pull requests; grouping keeps it to a handful a week.
- MegaLinter's image bundles its own tool versions, while mise pins the local and standalone ones. The two can drift: a finding can appear in CI and not on a laptop. The MegaLinter image digest is the reference, and Renovate bumps it.
- Early on, report-only runs produce a long list. Triage is a one-off cost and the comparison keeps it bounded.
- CI run time grows by one MegaLinter job; the comparison records each tool's time, so a slow tool can be dropped.

## Alternatives considered

- **One workflow per tool, built by hand:** the most control, and the most files to keep pinned and updated; every tool needs its own SARIF upload and its own version pin.
- **Trunk Check:** fast, hermetic and pins its tools, but it is vendor-owned (the tool is open source, the hosted parts are not) and it overlaps mise for tool pinning. Reconsider if MegaLinter proves too slow.
- **Super-Linter:** covers formatting and syntax well but has less security coverage than MegaLinter.
- **DefectDojo (an aggregator for findings):** a server to host and feed; far more than one repository needs. The GitHub Security tab does the job.
- **Dependabot for version updates:** does not update mise tools or Action commit pins with a version comment as well as Renovate does. Dependabot security alerts stay on.
- **Grype, pip-audit, `npm audit`:** see the table; Trivy covers all three, so the first stage keeps Grype only to measure the difference.
- **TruffleHog as the secret scanner:** its verification step sends a found key to the provider to test it. The report-only run uses `--no-verification`.

## Open questions

- Which of Trivy's and Gitleaks' secret scanners stays, once the comparison shows what each finds?
- Does the repository keep Trivy config alone, or add Checkov or KICS for Helm? The comparison decides.
- Does the Security tab (code scanning alerts) or a monthly written summary serve the people who triage?
- What do CrossGuard policies check, and when does `pulumi preview` run in CI? This belongs to the Pulumi stack's ADR (0034).
- Should the images the node builds be scanned in the same workflow, after `docker buildx bake`, or in a separate release job?
