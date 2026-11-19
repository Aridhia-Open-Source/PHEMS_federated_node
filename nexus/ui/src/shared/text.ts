// "repo_path" -> "Repo path", "IN_PROGRESS" -> "In progress": field names and enum values as
// sentence case text.
export const sentence = (name: string) => {
  const text = name.replace(/_/g, " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
};
