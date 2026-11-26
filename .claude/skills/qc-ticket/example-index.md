<!-- A made-up range, to show the shape of 00-index.md only. Never copy its titles or PRs. -->
# QC tickets: origin/main..origin/feature-x

Context from `feature-x` at 1a2b3c4d. 3 tickets.

| # | Ticket | PRs |
|---|---|---|
| 01 | [QC] Only project members can see and run saved queries | #1234, #1240 |
| 02 | [QC] Quotas set in the cluster limit how many tasks a project runs at once | #1301 |
| 03 | [QC] Task logs can be downloaded from the Tasks page | #1312 |

## Needs the dev team first

- **03:** the download needs the log store switched on for QC (`logs.store.enabled`). It is off today.

## Found while writing

- Deleting a saved query does not remove it from the project's search results until the page is reloaded.
