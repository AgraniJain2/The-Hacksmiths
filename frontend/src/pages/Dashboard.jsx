import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";
import GoogleConnectionCard from "../components/GoogleConnectionCard";
import StatusPill from "../components/StatusPill";
import { ROLE_LABELS, initials } from "../components/AppShell";
import { IconCheck } from "../components/icons";
import styles from "./Dashboard.module.css";

const ROADMAP = [
  { label: "Setup & Auth", done: true },
  { label: "Create Interview Request", done: true },
  { label: "Interviewer Pool Profile", done: true },
  { label: "Candidate Availability Collection", done: true },
  { label: "Interviewer Pool Feasibility Check", done: true },
  { label: "Candidate Slot Selection", done: true },
  { label: "N-Seat Interviewer Assignment", done: true },
  { label: "Event Creation & Dispatch", done: false },
  { label: "Post-Booking & Exception Handling", done: true },
];

function StaffQuickActions() {
  const [recent, setRecent] = useState(null);

  useEffect(() => {
    api
      .listRequests()
      .then((items) => setRecent(items.slice(0, 3)))
      .catch(() => setRecent([]));
  }, []);

  return (
    <div className={`glass-card ${styles.actionsCard}`}>
      <h3 className={styles.actionsTitle}>Interview requests</h3>
      <p className={styles.actionsSubtitle}>Create one, or check on ones already in flight.</p>
      <div className={styles.actionsButtons}>
        <Link to="/requests/new" className="btn btn-primary btn-sm">
          New request
        </Link>
        <Link to="/requests" className="btn btn-outline btn-sm">
          View all
        </Link>
      </div>
      {recent && recent.length > 0 && (
        <div className={styles.recentList}>
          {recent.map(({ request }) => (
            <Link key={request.request_id} to={`/requests/${request.request_id}`} className={styles.recentRow}>
              <span>{request.interview_type.replaceAll("_", " ")}</span>
              <StatusPill status={request.status} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function InterviewerQuickActions() {
  const [offerCount, setOfferCount] = useState(null);

  useEffect(() => {
    api
      .myOffers()
      .then((offers) => setOfferCount(offers.filter((o) => o.interview.seats[o.seat_index].status === "offered").length))
      .catch(() => setOfferCount(0));
  }, []);

  return (
    <div className={`glass-card ${styles.actionsCard}`}>
      <h3 className={styles.actionsTitle}>Your panel work</h3>
      <p className={styles.actionsSubtitle}>
        {offerCount === null ? "Checking your offers…" : offerCount > 0 ? `${offerCount} offer${offerCount > 1 ? "s" : ""} waiting on you.` : "No pending offers right now."}
      </p>
      <div className={styles.actionsButtons}>
        <Link to="/interviewer/offers" className="btn btn-primary btn-sm">
          My offers
        </Link>
        <Link to="/interviewer/profile" className="btn btn-outline btn-sm">
          Edit profile
        </Link>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const firstName = user?.name?.split(" ")[0];

  if (user?.role === "candidate") {
    return <Navigate to="/candidate" replace />;
  }

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

        {user?.role === "interviewer" ? <InterviewerQuickActions /> : <StaffQuickActions />}

        <div className={`glass-card ${styles.roadmapCard}`}>
          <h2 className={styles.roadmapTitle}>Scheduling workflow</h2>
          <p className={styles.roadmapSubtitle}>
            WorkHire's end-to-end flow, per <span className="font-mono">Documentation/WORKFLOW.md</span>.
            Stages 2 through 6 and 8 run against an in-memory demo backend — no database or real Google
            Calendar/Meet integration yet (see <span className="font-mono">Documentation/SCHEDULER.md</span>).
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
