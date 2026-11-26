---
name: qc-ticket
description: Draft QC tickets for a pull request or a range of commits (for example origin/main..origin/verify/all). Reads the PRs, their linked issues and the diff, checks what the automated tests and QA plans already cover, and writes short tickets that tell QC what to check by hand. Use when someone asks for QC tickets, QC test cases, or what QC should test.
---

# QC tickets

```
/qc-ticket 664                              one pull request
/qc-ticket origin/main..origin/verify/all   every PR in a range, merged or stacked
/qc-ticket origin/verify/all                the same range, against origin/main
/qc-ticket                                  the current branch's PR, else origin/main..HEAD
/qc-ticket 664 --create                     also open the issues on GitHub, after the drafts are shown
```

Without `--create` this only writes drafts. It never opens, edits or comments on GitHub issues unless asked.

Make your own calls and write any assumption in the index. Ask the person only before writing a ticket that needs the dev team first (step 5). In CI (`CI=true`) never ask.

## What QC does now

Keep this in mind for every ticket. Edit this list when it stops being true.

- The dev team deploys to QC from `dagster-develop`. For a range, write the tickets as if the whole range has reached `dagster-develop`. Tickets have no version line and normally no deploy steps.
- Baseline: QC is Azure (AKS). Results go on an Azure Files share, the node's databases are on an Azure PostgreSQL flexible server with TLS on a private address, Traefik has a public IP, and certificates come from cert-manager through Azure DNS. The e2e suites and CI run on a local kind cluster with none of these. QC runs with the admin UI and the operator on. Release `federated-node` in namespace `fn`, operator in `fn-operator`, tasks in `tasks`. QC is deployed by Flux from a shared deployment repository. QC testers have SuperUser access and full `kubectl` access.
- Never query QC's cluster while writing tickets: it may not be running, and the skill must work the same in CI. Work from the baseline above and the code. Write checks for how things should work on QC, and let QC find what does not. Commands in a ticket assume `kubectl` already points at QC and never name a context. To find a user's id, use `owned_by.id` on a record they created, or their page in the Keycloak admin console.
- The end-to-end suites cover the main task flow (their READMEs say what they cover and what they do not). QC time goes on what they miss and on what is risky.
- Pick one tool per ticket. A ticket that needs Postman for its setup or its main checks (permissions, routes with no screen) does all its checks in Postman as the right user, giving the request and the status code the code returns. The UI appears in it only where seeing something on a screen is the point ("it is on their Projects page"). How the UI shows a refusal (a clear error, nothing half-changed) is checked once per screen in the UI ticket, not in every permission ticket.
- A ticket that does not need Postman uses the nexus UI. `kubectl` for node config and deploy checks.
- QC has full `kubectl` access to the QC cluster. Setup they can do with `kubectl` (test Secrets, test settings, reading logs) is theirs to do: give them the exact commands. Do not write "needs kubectl access" lines.
- Any ticket that uses Postman links the collection under "Before you start": `[Postman collection](https://aridhia-open-source.github.io/PHEMS_federated_node/docs/beta/develop/2.x/api/)`, and says: to act as a user in Postman, set the environment's `username` and `password` to theirs. A check that sends a token by hand (an expired one, a refresh token, another realm's) also says to turn off the collection's automatic sign-in for that request, or the collection will replace the token.
- A change to how the node is provisioned or deployed (Pulumi templates, Flux, the site repository, the chart's install path) is the exception: QC tests that deploy themselves, as a new site would. Write two tickets. The first removes the node and Flux (keeping the keys needed to go back), builds QC's own private GitHub site repository with the tool the range adds (Pulumi, not files written by hand), copies QC's values and encrypted Secrets into it from the shared repository, and installs from it. The second makes changes through that repository and hands QC back to the shared repository. Every command in order.

## Steps

### 1. Gather

```bash
.claude/skills/qc-ticket/gather.sh <arg> > <scratchpad>/qc-context.md
```

It prints an index of the PRs, then each PR's description, the issues it closes or mentions (each printed once), the files changed by area, the commit under test and the branch it merges into, which PRs are still open, the test notes and QA plans at that commit, the routes nexus-api registers with the access check each one makes, and the open `[QC]` issues. PRs already on the base branch are left out. Use the route table for every route, and for which access a refusal needs. For a range, read the index first, then the PRs you need. `gh pr view <n>` gives a whole description when one was cut.

The linked issues usually say what the change is for better than the PR does. Use them for "What changed" and for what a user expects.

For UI and API changes, look at the diff to find which screens and routes changed. The context ends with the right `git diff` command for the ref; run it with `nexus/ui` and `nexus/api/app` as the paths.

### 2. Read what is already tested or planned

At the ref under test (`git show <ref>:<path>`):

- The e2e READMEs: what the suites cover and, more useful here, what they do not.
- The QA plans in `project/QA/`, if there are any. Do not copy a plan's case step by step, but a plan having a case is no reason to drop a ticket step 4 asks for. Never mention the plans in a ticket or the index. Where a plan disagrees with the code, the code wins.
- `known-issues.md` in the QA folder. Do not ticket a known issue. Write checks for what the change is meant to do, even where a known or suspected bug will make one fail. Never add setup steps that work around a known bug: the checks should hit it, so QC can confirm it. Every ticket with a check a known or suspected bug may affect lists that bug at its end under "Potential bugs to confirm", one plain line each saying what QC may see.
- The open `[QC]` issues at the end of the context. Do not write a ticket an open one already covers.

### 3. Drop what QC does not need

Leave these out. Do not list them anywhere:

- docs, ADRs, CI, dev tooling (mise, Tilt, devcontainers, dev scripts) and test-only changes
- refactors that change no behaviour
- changes a later PR in the range undoes
- PRs that only merge other PRs (release and stack PRs)
- anything the e2e suites already check end to end

### 4. Decide what needs a person

A change needs a QC check if any of these is true:

- It touches sign-in, roles, permissions or secrets. The e2e suites run as one admin, so they do not check these. **For a release or a big range, always include one sign-in and permissions ticket.** For one PR, only when it touches them.
- It changes the UI. There are no UI end-to-end tests.
- It talks to a real outside system the suites fake or skip (GitHub when the suites use Gitea, a real Keycloak, cloud storage).
- It changes how the node is provisioned or deployed (see "What QC does now").
- It behaves differently on Azure than on the local kind cluster that the e2e suites and CI use. Look for changes to: shared storage (Azure Files, mount options, file permissions), the database (Azure PostgreSQL: TLS required, no `postgres` role, private address), ingress, DNS and certificates (Traefik's public IP, cert-manager with Azure DNS), network policies (kind does not enforce them), image pulls (ghcr, not the local registry), Secrets and identity (Key Vault, workload identity), anything behind `on_aks` or `storage.azure` / `certs.azure` in the chart, and timeouts or retries that only show with real network delay. Ticket what such a change does on QC's Azure cluster, with the checks that would fail there and pass on kind.
- The e2e README lists it as not covered. Cases it lists as removed on purpose are not ticketed.

For a change in a risky area, cover the ways it should refuse as well as what it should do. Use every case below that the change touches and the code supports:

- **Sign-in and tokens:** no token, an expired access token, a refresh token used as an access token, a token from another realm, an account with no role, a wrong password.
- **Permissions:** each role and access level that should be refused, a user with no access at all, and access that has been removed or has run out.
- **Secrets:** values never come back in any response, list or log line, and a change replaces or keeps keys the way the code says.
- **Task isolation:** each thing a task should not reach (the internet, the node's services, other tasks' files and Secrets), plus the one thing it should (its own dataset).
- **Uploads and user input:** a value that is too big, the wrong type, or tries to escape a path, rejected with a clear error.

If nothing qualifies, say "No QC ticket needed" with one line why. That is a valid result. But a change that qualifies and that QC cannot test yet (QC's cluster lacks something, a setting is off, an image is missing) still gets its full ticket, listed under "Needs the dev team first" with what is missing. Never turn "QC cannot test this yet" into "no ticket needed".

### 5. Group into tickets

Group by what a tester would recognise ("who can see a project"), not by PR. Several PRs often make one ticket.

No overlap: each thing is checked in exactly one ticket, and not in an open `[QC]` issue. Do not write "Assumes ..." lines, and do not cross-reference ticket numbers in the checks.

If a change can be checked with what QC already has (its GitHub repositories, its accounts, its cluster), check it that way rather than writing a ticket that waits on the dev team. If a check needs setup QC does not have yet (a Keycloak group, a test repository), give the steps under "Before you start" rather than dropping the change.

If a ticket needs a task image, check whether CI publishes it (`gh api /orgs/Aridhia-Open-Source/packages/container/<name>`). If not, ask the person whether to add it to [Federated-Node-Example-App](https://github.com/Aridhia-Open-Source/Federated-Node-Example-App), where CI publishes test images. Until it exists, treat it like any other dev-team step.

If a ticket still needs the dev team to do something first (publish an image, deploy with a setting QC does not run with, change the cluster), ask the person before you write it: what is needed, whether it is ready, who will do it. If it is ready, write what QC needs under "Before you start". If not, put the ticket under "Needs the dev team first" in the index and leave it out of `--create`. In CI, do not ask: do the same.

How many: one PR, usually one ticket, sometimes none. A big range, 5 to 10. If you have more, merge related ones or drop the lowest risk.

### 6. Write each ticket

Use [template.md](template.md). Match the standard of [example.md](example.md) (setup with `kubectl` and a ready file) and [example-postman.md](example-postman.md) (a permission ticket done in Postman). The examples are made-up features: copy their shape and standard, never their routes, names or codes.

Check every concrete detail against the live code before you write it: route paths and bodies, error codes and messages, names of deployments, namespaces, sensors and pages, image names, and what a test tool prints. Do not guess a detail or copy it from a PR description. If you cannot confirm one, leave the check out.

- For a range, check details against the head of the PR that makes the change. Some files exist twice (an old copy left behind): find the live one from where the app registers its routes.
- If a ticket needs a chart setting QC does not already run with, check the images it runs are published on ghcr at QC's chart version. If one is missing, the ticket waits on the dev team.
- Check a task file's `env` against what the node accepts: nexus-api refuses some names and prefixes (`TASK_ENV_RESERVED_KEYS` and `TASK_ENV_RESERVED_PREFIXES`).
- A placeholder like `<run id>` is fine only for a value the tester reads off a screen or the cluster: say where to find it. Never for an owner, host, namespace or version: those are in "What QC does now" or the code. In a deploy ticket, give the command that reads a version off ghcr or the cluster instead.
- For one PR whose head cannot start (a missing module, a broken import), say so first in the index as a blocker. For a range, still write the tickets as if the range lands working, and put what stops it starting as one line under "Found while writing".

For each ticket, write `NN-<slug>.evidence.md` next to it: one numbered line per check, giving the file and line at the ref under test of the code that decides the expected result (a test can back it up, but never stands in for the code) (for example `3. nexus/api/app/projects_api.py:139 DELETE needs write on Project`). If you cannot find the line, the check is a guess: fix it or drop it. The evidence file is for reviewers, not QC, and is never posted.

Then run `python3 .claude/skills/qc-ticket/lint.py <drafts folder>` and fix every error. Fix each warning unless the ticket needs it (the length aim is soft). Run it again until it says clean.

Before you finish, reread each ticket as a tester who has not seen the code.

### 7. Save and show

Write the drafts to `<scratchpad>/qc-tickets/<range-or-pr>/`. With no scratchpad, as in CI, use `${RUNNER_TEMP:-${TMPDIR:-/tmp}}/qc-tickets/`.

- `00-index.md`, like [example-index.md](example-index.md): one commit line, a table of tickets with their PRs, then "Needs the dev team first" if any ticket waits on them, then "Found while writing" (at most five bugs, one line each, no file paths, for the dev team; a bug that affects a ticket also goes under that ticket's "Potential bugs to confirm"), then at most three lines of assumptions a tester needs. Never name a PR, plan case or feature that has no ticket, under any heading.
- `01-<slug>.md`, `02-<slug>.md` ...: one ticket each, first line the title, each with its `.evidence.md`.

Show the user the index and the paths.

### 8. Create (only with `--create` or when asked)

1. Check the open `[QC]` and `[Draft] [QC]` issues again. If one already covers the same thing, tell the user instead of making a second one.
2. Create each ticket as a draft for the dev to finish: `gh issue create --title "[Draft] <title>" --assignee <author of each PR the ticket lists> --body-file <body>`. The body starts with this line, then the ticket without its title line:

   > Draft for the dev to finish: check these steps against what you built and fill in anything marked `<...>`. When it is ready for QC, remove `[Draft]` from the title.

   Keep the **PRs:** and **Issues:** numbers as plain `#123`, never in backticks, so GitHub links each ticket to its PRs and shows it on their timelines. Never use closing words ("Closes #..."): merging the PR would close the QC ticket. Never post the `.evidence.md` files. Tickets under "Needs the dev team first" are created the same way: the dev finishing the draft is the one to unblock it.
3. Print the issue links.

### 9. Improve this skill from feedback

When the person asks for a change to a ticket, fix the ticket, then ask yourself whether the same change would apply to tickets from future runs. If it would (a rule about what to leave out, what QC can do, how to word something, a fact about the QC setup), add it to this skill in the same session, in the section it belongs to, and say so in one line. Keep the rule general: no ticket numbers or one-off details. If the change only fits this one ticket, leave the skill alone.

## Writing rules

The reader is a tester who knows the product but has not read the code. They want to know what to do and what they should see.

- **Title:** `[QC] ` and what to check, in plain words. `[QC] Users only see the projects they have access to`, not `[QC] Cedar authorization grants`.
- **What changed:** under 60 words on what is different for someone using the node. No namespaces, sensors, tools or style names.
- **Before you start:** what QC needs, one line each. For accounts, repositories or data QC already has or knows how to make, write `Needs ...` only.
- **Checks:** at most eight. One action and one result per check, under 40 words, not counting a command block. Every refusal check gives the request (or command) and the status code. If the checks do not fit in eight, split the ticket in two rather than chaining actions. Write the result as a sentence ("It is refused and nothing changes"), with a status code or message only when the check is about it. Aim for under 350 words per ticket, not counting files and commands the tester copies. That is a soft aim: go over when the checks need it, but cut padding, never a needed check.
- **Every action says how:** the UI page and button, the Postman request (method, path, and body if needed), or the exact command. "X still works" or "give them access" on its own is not a check. Before writing that something works, confirm in the code that it is built at all.
- **Name people with their role** every time: "Admin A", "Admin B", "User U", "the SuperUser". Never a bare "A" or "U", in "Before you start" or in the checks.
- **Give what they need, ready to use.** If a check needs a file, a task file or a command, put it in the ticket, filled in for QC. Never "copy X from the repo and change it". Test data uses made-up values and never touches QC's real setup. Made-up email addresses and domains use `example.org` (for example `qc-admin@example.org`), never a placeholder.
- **Short words.** "check", not "validate". "use", not "leverage". "see", not "observe". "works", not "functions as expected".
- **Leave out** file names, class names, ADR numbers, branch names and internal component names, unless the tester sees them on screen. No background on why the feature exists. No hedging.
- **Never put anything sensitive in a ticket: they are public.** No kube context or cluster names, IP addresses, private hostnames or QC's address, cloud resource names (database servers, storage accounts, resource groups, Key Vaults, subscription or tenant ids), private repository names, email addresses, tokens, passwords, keys or Secret values. Write "point `kubectl` at QC", "QC's address", "the shared deployment repository". Where a command needs a QC-specific value (an address, the shared repository, a Flux name), have the tester's command read it off QC's cluster into a shell variable first (for example `REPO=$(kubectl get gitrepository -n flux-system -o jsonpath='{.items[0].spec.url}')`), and assume `kubectl` already points at QC. The one exception is the cloud metadata address `169.254.169.254`, which is the same everywhere.
- No em dashes. Use a comma or a full stop.

Too much:

> - [ ] Verify that when a user possessing only the `read` relation on a Project entity attempts to perform a mutating operation (PATCH/DELETE) via the API, the Cedar policy engine correctly denies the request and returns an HTTP 403 Forbidden response, and that the decision log records the rule identifier.

Right:

> - [ ] As a user with read access, try to edit the project. You get an error and nothing changes.
