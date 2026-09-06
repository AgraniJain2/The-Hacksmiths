import { useTheme } from "../context/ThemeContext";
import { IconMoon, IconSun } from "./icons";
import styles from "./ThemeToggle.module.css";

/** A real switch (role="switch"), not a button-that-looks-like-an-icon —
 * per the brief's "toggle switch for light and dark mode". */
export default function ThemeToggle() {
  const { isDark, toggleTheme } = useTheme();

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isDark}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className={styles.switch}
      onClick={toggleTheme}
    >
      <IconSun className={`${styles.icon} ${styles.iconSun}`} />
      <IconMoon className={`${styles.icon} ${styles.iconMoon}`} />
      <span className={styles.thumb} />
    </button>
  );
}
