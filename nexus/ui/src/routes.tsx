// The one place pages are registered. Fan-out agents never edit this file.
import type { ComponentType } from "react";
import Secrets from "./pages/secrets";
import Providers from "./pages/providers";
import TriggerRepos from "./pages/trigger-repos";
import ResultsRepos from "./pages/results-repos";
import Datasets from "./pages/datasets";
import Projects from "./pages/projects";

export const pages: { path: string; label: string; element: ComponentType }[] = [
  { path: "global/secrets", label: "Secrets", element: Secrets },
  { path: "global/providers", label: "Git providers", element: Providers },
  { path: "global/repositories/triggers", label: "Trigger repositories", element: TriggerRepos },
  { path: "global/repositories/results", label: "Results repositories", element: ResultsRepos },
  { path: "global/datasets", label: "Datasets", element: Datasets },
  { path: "projects", label: "Projects", element: Projects },
];
