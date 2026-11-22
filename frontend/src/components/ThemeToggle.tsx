import { useTheme } from "../hooks/useTheme";
import { IconButton } from "./Button";
import { MoonIcon, SunIcon } from "./Icons";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <IconButton
      label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      tooltip={theme === "dark" ? "Light mode" : "Dark mode"}
      onClick={toggle}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
    </IconButton>
  );
}
