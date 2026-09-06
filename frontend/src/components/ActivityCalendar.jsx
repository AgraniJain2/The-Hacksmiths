import styles from "./ActivityCalendar.module.css";
import { IconCalendar } from "./icons";

const DAY_FORMAT = { weekday: "short", month: "short", day: "numeric" };
const TIME_FORMAT = { hour: "numeric", minute: "2-digit" };

function dayKey(date) {
  return date.toDateString();
}

/**
 * Agenda-style "assigned activities" widget shared by the dashboard (staff/
 * interviewer) and the candidate page — one list, grouped by day, sorted
 * soonest-first. Each caller aggregates its own role's events from the
 * endpoints it already calls (requests/offers/my-request) into the shape
 * below; this component only renders, it never fetches.
 *
 * `events`: [{ id, title, subtitle?, start: Date, status?: ReactNode }]
 */
export default function ActivityCalendar({ events, emptyLabel = "Nothing scheduled yet." }) {
  const sorted = [...events].sort((a, b) => a.start - b.start);

  const groups = [];
  for (const event of sorted) {
    const key = dayKey(event.start);
    let group = groups.find((g) => g.key === key);
    if (!group) {
      group = { key, date: event.start, items: [] };
      groups.push(group);
    }
    group.items.push(event);
  }

  return (
    <div className={`glass-card ${styles.card}`}>
      <div className={styles.header}>
        <IconCalendar width={18} height={18} />
        <h3 className={styles.title}>Upcoming activity</h3>
      </div>

      {groups.length === 0 ? (
        <p className={`text-secondary ${styles.empty}`}>{emptyLabel}</p>
      ) : (
        <div className={styles.groups}>
          {groups.map((group) => (
            <div key={group.key} className={styles.group}>
              <div className={styles.dayLabel}>{group.date.toLocaleDateString(undefined, DAY_FORMAT)}</div>
              <div className={styles.items}>
                {group.items.map((event) => (
                  <div key={event.id} className={styles.item}>
                    <span className={styles.time}>{event.start.toLocaleTimeString(undefined, TIME_FORMAT)}</span>
                    <span className={styles.itemBody}>
                      <span className={styles.itemTitle}>{event.title}</span>
                      {event.subtitle && <span className={styles.itemSubtitle}>{event.subtitle}</span>}
                    </span>
                    {event.status}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
