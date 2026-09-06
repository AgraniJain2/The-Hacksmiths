import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import Logo from "./Logo";
import ThemeToggle from "./ThemeToggle";
import BackgroundFX from "./BackgroundFX";
import { IconLogout } from "./icons";
import styles from "./AppShell.module.css";

const ROLE_LABELS = {
  recruiter: "Recruiter",
  hiring_manager: "Hiring manager",
  interviewer: "Interviewer",
  candidate: "Candidate",
};

function initials(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase();
}

function navLinksForRole(role) {
  const shared = [{ to: "/settings/google", label: "Google" }];
  if (role === "candidate") {
    return [{ to: "/candidate", label: "My interview" }, ...shared, { to: "/notifications", label: "Notifications" }];
  }
  if (role === "interviewer") {
    return [
      { to: "/dashboard", label: "Dashboard" },
      { to: "/interviewer/offers", label: "My offers" },
      { to: "/interviewer/profile", label: "My profile" },
      ...shared,
      { to: "/notifications", label: "Notifications" },
    ];
  }
  // recruiter / hiring_manager
  return [
    { to: "/dashboard", label: "Dashboard" },
    { to: "/requests", label: "Requests" },
    ...shared,
    { to: "/notifications", label: "Notifications" },
  ];
}

/**
 * Layout for every authenticated page: sticky nav (logo, primary nav, theme
 * toggle, user chip) + centered content column. Add a new authenticated
 * page as a child route of this one in App.jsx — don't rebuild the nav.
 */
export default function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className={styles.shell}>
      <BackgroundFX />
      <header className={styles.nav}>
        <Logo size="sm" />
        <nav className={styles.navLinks}>
          {navLinksForRole(user?.role).map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) => `${styles.navLink} ${isActive ? styles.navLinkActive : ""}`}
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.navActions}>
          <ThemeToggle />
          <span className={styles.userChip}>
            <span className={styles.avatar}>{initials(user?.name)}</span>
            <span className={styles.userMeta}>
              <span className={styles.userName}>{user?.name}</span>
              <span className="text-muted" style={{ fontSize: "0.68rem" }}>
                {ROLE_LABELS[user?.role] || user?.role}
              </span>
            </span>
          </span>
          <button className="btn btn-ghost btn-sm" onClick={handleLogout} aria-label="Log out">
            <IconLogout width={16} height={16} />
          </button>
        </div>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}

export { ROLE_LABELS, initials };
