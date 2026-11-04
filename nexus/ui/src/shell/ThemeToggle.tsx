import { Button, Icon } from "@/ui";

import { shellMessages } from "./messages";
import { useTheme } from "./theme";

/** Round sun/moon button: shows where a press takes you (sun in dark mode, moon in light). */
export function ThemeToggle({ onBlue = false }: { onBlue?: boolean }) {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <Button
      type="button"
      variant="secondary"
      size="icon"
      onBlue={onBlue}
      aria-label={dark ? shellMessages.theme.toLight : shellMessages.theme.toDark}
      onClick={toggle}
    >
      <Icon name={dark ? "sun" : "moon"} size="md" />
    </Button>
  );
}
