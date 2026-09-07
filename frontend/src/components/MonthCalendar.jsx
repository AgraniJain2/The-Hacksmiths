import { useMemo, useState } from "react";
import styles from "./MonthCalendar.module.css";
import { IconCalendar } from "./icons";
import { formatDay, formatTime } from "../lib/datetime";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_LABEL = { month: "long", year: "numeric" };

function dayKey(date) {
  return date.toDateString();
}

function startOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

/** 6 full weeks (42 days) covering `month`, including the leading/trailing
 * days from the adjacent months needed to fill the grid. */
function buildWeeks(month) {
  const first = startOfMonth(month);
  const gridStart = new Date(first);
  gridStart.setDate(first.getDate() - first.getDay());

  const days = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    days.push(d);
  }
  const weeks = [];
  for (let i = 0; i < days.length; i += 7) weeks.push(days.slice(i, i + 7));
  return weeks;
}

/**
 * A real month-grid calendar — recruiter dashboard only. Presentational,
 * same event shape ActivityCalendar already uses
 * (`{ id, title, subtitle?, start: Date, status? }`); never fetches.
 */
export default function MonthCalendar({ events, emptyLabel = "Nothing scheduled yet." }) {
  const today = useMemo(() => new Date(), []);
  const [month, setMonth] = useState(() => startOfMonth(today));
  const [selectedKey, setSelectedKey] = useState(null);

  const eventsByDay = useMemo(() => {
    const map = new Map();
    for (const event of events) {
      const key = dayKey(event.start);
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(event);
    }
    for (const list of map.values()) list.sort((a, b) => a.start - b.start);
    return map;
  }, [events]);

  const weeks = useMemo(() => buildWeeks(month), [month]);
  const todayKey = dayKey(today);
  const selectedEvents = selectedKey ? eventsByDay.get(selectedKey) || [] : [];
  const selectedDate = selectedKey
    ? weeks.flat().find((d) => dayKey(d) === selectedKey)
    : null;

  function changeMonth(delta) {
    setMonth((m) => new Date(m.getFullYear(), m.getMonth() + delta, 1));
  }

  return (
    <div className={`glass-card ${styles.card}`}>
      <div className={styles.header}>
        <div className={styles.title}>
          <IconCalendar width={18} height={18} />
          <h3>{month.toLocaleDateString(undefined, MONTH_LABEL)}</h3>
        </div>
        <div className={styles.nav}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => changeMonth(-1)}>
            ‹
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setMonth(startOfMonth(today))}
          >
            Today
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => changeMonth(1)}>
            ›
          </button>
        </div>
      </div>

      <div className={styles.weekdays}>
        {WEEKDAY_LABELS.map((w) => (
          <span key={w}>{w}</span>
        ))}
      </div>

      <div className={styles.grid}>
        {weeks.flat().map((date) => {
          const key = dayKey(date);
          const dayEvents = eventsByDay.get(key) || [];
          const inMonth = date.getMonth() === month.getMonth();
          const isToday = key === todayKey;
          const isSelected = key === selectedKey;
          return (
            <button
              type="button"
              key={key}
              className={[
                styles.cell,
                !inMonth && styles.outside,
                isToday && styles.today,
                isSelected && styles.selected,
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => setSelectedKey(isSelected ? null : key)}
            >
              <span className={styles.cellDate}>{date.getDate()}</span>
              {dayEvents.length > 0 && (
                <span className={styles.dots}>
                  {dayEvents.slice(0, 3).map((e) => (
                    <span key={e.id} className={styles.dot} />
                  ))}
                  {dayEvents.length > 3 && <span className={styles.dotMore}>+{dayEvents.length - 3}</span>}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {selectedKey ? (
        <div className={styles.dayDetail}>
          <div className={styles.dayDetailHeader}>{formatDay(selectedDate)}</div>
          {selectedEvents.length === 0 ? (
            <p className={`text-secondary ${styles.empty}`}>Nothing scheduled this day.</p>
          ) : (
            <div className={styles.dayDetailList}>
              {selectedEvents.map((e) => (
                <div key={e.id} className={styles.dayDetailItem}>
                  <span className={styles.dayDetailTime}>{formatTime(e.start)}</span>
                  <span className={styles.dayDetailBody}>
                    <span className={styles.dayDetailTitle}>{e.title}</span>
                    {e.subtitle && <span className={styles.dayDetailSubtitle}>{e.subtitle}</span>}
                  </span>
                  {e.status}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        events.length === 0 && <p className={`text-secondary ${styles.empty}`}>{emptyLabel}</p>
      )}
    </div>
  );
}
