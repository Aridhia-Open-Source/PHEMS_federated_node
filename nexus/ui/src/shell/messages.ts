// User-facing text for the nexus shell and login page.
export const shellMessages = {
  appName: "Federated Node",
  menuTitle: "Menu",
  menuDescription: "Federated Node admin",
  logOut: "Log out",
  navGroups: { projects: "Projects", global: "Global" },
  theme: { toLight: "Switch to light theme", toDark: "Switch to dark theme" },
  login: {
    title: "Federated Node",
    description: "Log in to the admin console.",
    username: "Username",
    password: "Password",
    action: "Log in",
    noToken: "Login response had no token",
  },
  // Wording of the widgets in shared/
  widgets: {
    table: {
      empty: "Nothing here yet",
      previous: "Previous",
      next: "Next",
      page: (page: number, pages: number, total: number) => `Page ${page} of ${pages} (${total} total)`,
    },
    delete: "Delete",
    revoke: "Revoke",
    restore: "Restore",
    unassign: "Unassign",
    deleteDescription: "This can't be undone.",
    revokeDescription: "It is withdrawn from every project. You can restore it later.",
    unassignDescription: "The project loses access to it. You can assign it again later.",
    force: "Delete even if projects use it",
    enabled: "Enabled",
    save: "Save",
    choose: "Choose one",
    invalidJson: (label: string) => `Enter valid JSON in ${label}.`,
    jsonLabel: "JSON",
    healthcheck: { title: "Healthcheck", run: "Run healthcheck" },
    usedBy: { title: "Used by", empty: "No project uses this" },
    backTo: (what: string) => `Back to ${what}`,
    statusOk: "OK",
  },
  // Titles and actions of the pages in pages/
  pages: {
    edit: "Edit",
    delete: "Delete",
    loading: "Loading…",
    secrets: {
      title: "Secrets", back: "secrets", new: "New secret", detail: (label: string) => `Secret ${label}`,
      setValues: "Set values",
    },
    providers: {
      title: "Git providers", back: "git providers", new: "New provider", newTitle: "New git provider",
      detail: (name: string) => `Git provider ${name}`,
    },
    triggerRepos: {
      title: "Trigger repositories", back: "trigger repositories", new: "New trigger repository",
      detail: (path: string) => `Trigger repository ${path}`,
    },
    resultsRepos: {
      title: "Results repositories", back: "results repositories", new: "New results repository",
      detail: (path: string) => `Results repository ${path}`,
    },
    datasets: { title: "Datasets", back: "datasets", new: "New dataset", detail: (name: string) => `Dataset ${name}` },
    resources: {
      title: "Resources",
      assign: (kind: string) => `Assign ${kind.toLowerCase()}`,
      pickFirst: "Choose one from the list first.",
    },
    resourceDetail: {
      back: "resources", global: "Global resource", settings: "Settings", state: "State",
      raw: "Raw response", pullRequests: "Pull requests",
    },
    triggers: {
      intro: "The project's trigger repositories. Pick one for its pull requests.",
      back: "triggers", backToPullRequests: "pull requests",
      pullRequestsOf: (repo: string) => `Pull requests of ${repo}`,
      pullRequest: (number: number) => `Pull request #${number}`,
      projectResource: "Project resource", resource: "Resource", task: "Task", taskLink: (id: number) => `Task ${id}`,
      noTask: "No task yet", stateFilter: "State", allStates: "All",
    },
    tasks: {
      back: "tasks", detail: (id: number, name: string) => `Task ${id}: ${name}`,
      pullRequest: "Pull request:", config: "Config", results: "Results", logs: "Logs", loadLogs: "Load logs",
    },
    health: { rerun: "Re-run", projectStatus: "Project status:", noResults: " (no results repository assigned)" },
    results: { back: "results", detail: (id: number) => `Result ${id}` },
    projects: {
      title: "Projects", back: "projects", new: "New project", detail: (name: string) => `Project ${name}`,
      newIntro: "Projects start disabled. Assign repositories, datasets and secrets, then enable it.",
      tabsLabel: "Project sections",
      tabs: {
        overview: "Overview", resources: "Resources", health: "Healthcheck", triggers: "Triggers",
        tasks: "Tasks", results: "Results",
      },
    },
  },
} as const;
