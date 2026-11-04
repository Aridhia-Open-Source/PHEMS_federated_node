// User-facing default text for shared components lives here, not inline in components,
// so it can be swapped for translations later in one place. Components also take these
// as props, so an app can pass its own wording.
export const messages = {
  skipToContent: "Skip to main content",
  openMenu: "Open menu",
  closeMenu: "Close menu",
  menuTitle: "Menu",
  search: { label: "Search" },
  datasetCard: {
    draft: "Draft",
    overdue: "Overdue",
    reminder: "Revalidation due",
  },
  tagInput: { remove: "Remove" },
  repeatableList: { add: "Add", remove: "Remove" },
  required: "(required)",
  loading: "Loading…",
  copy: "Copy",
  copied: "Copied",
  copyFailed: "Could not copy",
  cancel: "Cancel",
  confirm: "Confirm",
  statusDraft: "Draft",
  statusPublished: "Published",
  detail: { empty: "Not provided" },
  feedback: { dismiss: "Dismiss", notifications: "Notifications" },
} as const;
