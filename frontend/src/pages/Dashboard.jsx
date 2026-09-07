import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";
import GoogleConnectionCard from "../components/GoogleConnectionCard";
import ActivityCalendar from "../components/ActivityCalendar";
import MonthCalendar from "../components/MonthCalendar";
import StatusPill from "../components/StatusPill";
import { IconAlert } from "../components/icons";
import { ROLE_LABELS, initials } from "../components/AppShell";
import styles from "./Dashboard.module.css";

const OPEN_REQUEST_STATUSES = new Set([
  "collecting_availability",
  "awaiting_candidate_selection",
  "assigning_panel",
  "manual_scheduling_required",
]);

function StatTile({ label, value }) {
  return (
    <div className={`glass-card ${styles.statTile}`}>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  );
}

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

function InterviewerQuickActions({ offerCount }) {
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

/** Recruiter/hiring manager: open-request count + confirmed-interview calendar. */
function useStaffActivity() {
  const [state, setState] = useState({ loading: true, stats: null, events: [] });

  useEffect(() => {
    api
      .listRequests()
      .then((items) => {
        const now = new Date();
        const openCount = items.filter(({ request }) => OPEN_REQUEST_STATUSES.has(request.status)).length;
        const upcoming = items.filter(({ interview }) => interview && new Date(interview.slot_start) >= now);
        setState({
          loading: false,
          stats: [
            { label: "Open requests", value: openCount },
            { label: "Upcoming interviews", value: upcoming.length },
          ],
          events: upcoming.map(({ request, interview }) => ({
            id: interview.interview_id,
            title: request.interview_type.replaceAll("_", " "),
            subtitle: request.candidate_id,
            start: new Date(interview.slot_start),
            status: <StatusPill status={interview.status} />,
          })),
        });
      })
      .catch(() => setState({ loading: false, stats: [], events: [] }));
  }, []);

  return state;
}

/** Interviewer: pending-offer count + a calendar of seats they've actually accepted. */
function useInterviewerActivity() {
  const [state, setState] = useState({ loading: true, stats: null, events: [], offerCount: null });

  useEffect(() => {
    api
      .myOffers()
      .then((offers) => {
        const now = new Date();
        const seatOf = (o) => o.interview.seats[o.seat_index];
        const pending = offers.filter((o) => seatOf(o).status === "offered");
        const accepted = offers.filter(
          (o) => seatOf(o).status === "accepted" && new Date(o.interview.slot_start) >= now
        );
        setState({
          loading: false,
          offerCount: pending.length,
          stats: [
            { label: "Pending offers", value: pending.length },
            { label: "Confirmed seats", value: accepted.length },
          ],
          events: accepted.map((o) => ({
            id: `${o.interview.interview_id}-${o.seat_index}`,
            title: o.interview.interview_type.replaceAll("_", " "),
            subtitle: "Panel seat confirmed",
            start: new Date(o.interview.slot_start),
            status: <StatusPill status={seatOf(o).status} kind="seat" />,
          })),
        });
      })
      .catch(() => setState({ loading: false, stats: [], events: [], offerCount: 0 }));
  }, []);

  return state;
}

export default function Dashboard() {
  const { user } = useAuth();
  const firstName = user?.name?.split(" ")[0];
  const isInterviewer = user?.role === "interviewer";

  const staffActivity = useStaffActivity();
  const interviewerActivity = useInterviewerActivity();
  const activity = isInterviewer ? interviewerActivity : staffActivity;

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

      {isInterviewer && user?.google_connected === false && (
        <div className={styles.reauthBanner}>
          <IconAlert width={16} height={16} style={{ display: "inline", verticalAlign: "-3px", marginRight: 6 }} />
          Your Google connection needs to be reconnected — until then, requests can't check your
          calendar and you may quietly miss out on panel offers. Sign out and back in with Google
          to fix it, or see{" "}
          <Link to="/settings/google" className={styles.reauthLink}>
            Google connection
          </Link>
          .
        </div>
      )}

      {activity.stats && activity.stats.length > 0 && (
        <div className={styles.statsRow}>
          {activity.stats.map((s) => (
            <StatTile key={s.label} label={s.label} value={s.value} />
          ))}
        </div>
      )}

      <div className={styles.grid}>
        <div className={`glass-card ${styles.profileCard}`}>
          <span className={styles.avatar}>{initials(user?.name)}</span>
          <div>
            <div className={styles.profileName}>{user?.name}</div>
            <div className={styles.profileEmail}>{user?.email}</div>
          </div>
        </div>

        <GoogleConnectionCard variant="summary" />

        {isInterviewer ? (
          <InterviewerQuickActions offerCount={interviewerActivity.offerCount} />
        ) : (
          <StaffQuickActions />
        )}

        {!isInterviewer && (
          <div className={styles.calendarSpan}>
            <MonthCalendar
              events={activity.events}
              emptyLabel={activity.loading ? "Loading…" : "No confirmed interviews coming up."}
            />
          </div>
        )}

        <div className={styles.calendarSpan}>
          <ActivityCalendar
            events={activity.events}
            emptyLabel={
              activity.loading
                ? "Loading…"
                : isInterviewer
                ? "No confirmed panel seats coming up."
                : "No confirmed interviews coming up."
            }
          />
        </div>
      </div>
    </div>
  );
}
