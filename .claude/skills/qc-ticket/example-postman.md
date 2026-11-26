<!-- A made-up feature, to show the standard for a permission ticket: every check in Postman as the right user, with the request and the status code, the UI only where seeing something on screen is the point, results as sentences. Never copy its routes, names or codes: check the real ones in the code. -->
[QC] Only project members can see and run saved queries

**PRs:** #1234, #1240

### What changed

Projects can now keep saved queries. Anyone with access to a project can see its saved queries and run them. Only an admin can add, change or delete one.

### Before you start

- Needs an admin and a plain user with no admin role, both with access to one project, and a second plain user with no access to it.
- Use the [Postman collection](https://aridhia-open-source.github.io/PHEMS_federated_node/docs/beta/develop/2.x/api/). To act as a user in Postman, set the environment's `username` and `password` to theirs.

### Checks

- [ ] As the admin, `POST /projects/<id>/saved-queries` with `{"name": "qc-count", "sql": "SELECT count(*) FROM person"}`. It returns 201 with the query's id.
- [ ] As the plain user with access, `POST /projects/<id>/saved-queries/<query id>/run`. It returns 200 with a result.
- [ ] As the plain user with access, `DELETE /projects/<id>/saved-queries/<query id>`. It returns 409 and the query is still listed by `GET /projects/<id>/saved-queries`.
- [ ] As the user with no access, `GET /projects/<id>/saved-queries`. It returns 404.
- [ ] As the plain user with access, open the project's Saved queries tab. `qc-count` is listed.
- [ ] As the admin, `DELETE /projects/<id>/saved-queries/<query id>`. It returns 204 and the query is gone from the Saved queries tab.
