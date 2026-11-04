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
} as const;
