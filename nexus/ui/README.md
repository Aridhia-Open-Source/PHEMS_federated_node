# nexus-ui

React admin UI for nexus-api, served under `/nexus-ui/`.

## Screenshots

`npm run screenshots` logs in and saves a full-page PNG of every core screen in dark mode:
login, the projects list with its create form and delete dialog, one project's tabs and
detail pages, the global lists, and a mobile (390x844) shot with the side menu open.
It is read-only: it never submits a form or confirms a delete.

One-time setup, from `nexus/ui` (the script needs Playwright and a browser):

```sh
npm install -D playwright
npx playwright install chromium
```

Then, with the dev cluster up (`tilt up`):

```sh
npm run screenshots
```

Files land in `~/nexus-ui-screenshots/<today>/`, numbered in menu order (`01-login.png`,
`02-projects.png`, ...). Pages come from the side menu and the links on each page, so a
new page in `src/routes.tsx` is picked up without changing the script.

| Variable      | Default                                                 |
| ------------- | ------------------------------------------------------- |
| `UI_URL`      | `http://localhost:8088/nexus-ui/`                       |
| `FN_USER`     | `KEYCLOAK_FIRST_USER_EMAIL` from the repo `.dev.env`    |
| `FN_PASSWORD` | `KEYCLOAK_FIRST_USER_PASSWORD` from the repo `.dev.env` |
| `OUT_DIR`     | `~/nexus-ui-screenshots/<today>`                        |
