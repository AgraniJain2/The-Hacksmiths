import { useAuth } from "../context/AuthContext";
import GoogleConnectionCard from "../components/GoogleConnectionCard";
import { ROLE_LABELS, initials } from "../components/AppShell";
import { IconCheck } from "../components/icons";
import styles from "./Dashboard.module.css";

const ROADMAP = [
  { label: "Setup & Auth", done: true },
  { label: "Create Interview Request", done: false },
  { label: "Interviewer Pool Profile", done: false },
  { label: "Candidate Availability Collection", done: false },
  { label: "Interviewer Pool Feasibility Check", done: false },
  { label: "Candidate Slot Selection", done: false },
  { label: "N-Seat Interviewer Assignment", done: false },
  { label: "Event Creation & Dispatch", done: false },
  { label: "Post-Booking & Exception Handling", done: false },
];

export default function Dashboard() {
  const { user } = useAuth();
  const firstName = user?.name?.split(" ")[0];

  return (
    <div className="animate-in">
      <div className={styles.header}>
        <div>
          <h1 className={`heading-display ${styles.greeting}`}>Welcome back, {firstName}</h1>
          <p className={styles.greetingSub}>
            <span className={`pill role-${user?.role}`}>{ROLE_LABELS[user?.role] || user?.role}</span>
          </p>
        </div>
      </div>

      <div className={styles.grid}>
        <div className={`glass-card ${styles.profileCard}`}>
          <span className={styles.avatar}>{initials(user?.name)}</span>
          <div>
            <div className={styles.profileName}>{user?.name}</div>
            <div className={styles.profileEmail}>{user?.email}</div>
          </div>
        </div>

        <GoogleConnectionCard variant="summary" />

        <div className={`glass-card ${styles.roadmapCard}`}>
          <h2 className={styles.roadmapTitle}>Scheduling workflow</h2>
          <p className={styles.roadmapSubtitle}>
            WorkHire's end-to-end flow, per{" "}
            <span className="font-mono">Documentation/WORKFLOW.md</span>. Only Setup & Auth is live — the
            rest lands as each module is built.
          </p>
          <div className={styles.roadmapList}>
            {ROADMAP.map((step, i) => (
              <div key={step.label} className={`${styles.roadmapItem} ${step.done ? styles.roadmapItemDone : ""}`}>
                <span className={styles.roadmapStep}>{String(i + 1).padStart(2, "0")}</span>
                <span className={styles.roadmapLabel}>{step.label}</span>
                {step.done ? (
                  <span className="pill pill-success">
                    <IconCheck width={12} height={12} /> Live
                  </span>
                ) : (
                  <span className="pill pill-neutral">Coming soon</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
