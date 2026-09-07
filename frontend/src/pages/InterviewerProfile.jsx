import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { INTERVIEWER_QUALIFICATION_TYPES, SENIORITY_LEVELS, SKILLS } from "../lib/constants";
import { TIMEZONES, browserTimezone } from "../lib/timezones";
import Spinner from "../components/Spinner";
import styles from "./InterviewerProfile.module.css";

const empty = {
  skills: [],
  seniority: "MID",
  interview_types: [],
  timezone: "",
  working_hours_start: "09:00",
  working_hours_end: "18:00",
  active: true,
};

export default function InterviewerProfile() {
  const navigate = useNavigate();
  const [form, setForm] = useState(empty);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getMyInterviewerProfile()
      .then((p) => {
        if (p) {
          setForm({
            skills: p.skills,
            seniority: p.seniority,
            interview_types: p.interview_types,
            timezone: p.timezone,
            working_hours_start: p.working_hours.start,
            working_hours_end: p.working_hours.end,
            active: p.active,
          });
        } else {
          setForm((f) => ({ ...f, timezone: browserTimezone() }));
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function toggleType(t) {
    setForm((f) => ({
      ...f,
      interview_types: f.interview_types.includes(t)
        ? f.interview_types.filter((x) => x !== t)
        : [...f.interview_types, t],
    }));
  }

  function toggleSkill(s) {
    setForm((f) => ({
      ...f,
      skills: f.skills.includes(s) ? f.skills.filter((x) => x !== s) : [...f.skills, s],
    }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (form.interview_types.length === 0) throw new Error("Pick at least one interview type.");
      if (form.skills.length === 0) throw new Error("Pick at least one skill.");
      await api.saveMyInterviewerProfile({
        skills: form.skills,
        seniority: form.seniority,
        interview_types: form.interview_types,
        timezone: form.timezone,
        working_hours_start: form.working_hours_start,
        working_hours_end: form.working_hours_end,
        active: form.active,
      });
      navigate("/dashboard");
    } catch (err) {
      setError(err.message || "Couldn't save your profile.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Spinner label="Loading your profile…" />;

  return (
    <div className={`animate-in ${styles.wrap}`}>
      <div className={styles.header}>
        <h1 className={`heading-display ${styles.heading}`}>Interviewer profile</h1>
        <p className={styles.subtitle}>
          What you're qualified for and when you're reachable — this is what the panel-assignment
          engine matches requests against.
        </p>
      </div>

      <form className={`glass-card ${styles.card}`} onSubmit={handleSubmit}>
        <div className="form-grid">
          <div className="field field-span-2">
            <label className="field-label">Skills</label>
            <div className={styles.typesGrid}>
              {Array.from(new Set([...SKILLS, ...form.skills])).map((s) => (
                <label key={s} className={styles.typeChip}>
                  <input type="checkbox" checked={form.skills.includes(s)} onChange={() => toggleSkill(s)} />
                  {s}
                </label>
              ))}
            </div>
            <span className="field-hint">Pick every skill you can interview for.</span>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="seniority">
              Your seniority
            </label>
            <select id="seniority" className="select" value={form.seniority} onChange={(e) => set("seniority", e.target.value)}>
              {SENIORITY_LEVELS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="tz">
              Timezone
            </label>
            <select id="tz" className="select" value={form.timezone} onChange={(e) => set("timezone", e.target.value)}>
              {TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="wh_start">
              Working hours start
            </label>
            <input id="wh_start" type="time" className="input" value={form.working_hours_start} onChange={(e) => set("working_hours_start", e.target.value)} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="wh_end">
              Working hours end
            </label>
            <input id="wh_end" type="time" className="input" value={form.working_hours_end} onChange={(e) => set("working_hours_end", e.target.value)} />
          </div>

          <div className="field field-span-2">
            <label className="field-label">Qualified interview types</label>
            <div className={styles.typesGrid}>
              {INTERVIEWER_QUALIFICATION_TYPES.map((t) => (
                <label key={t} className={styles.typeChip}>
                  <input type="checkbox" checked={form.interview_types.includes(t)} onChange={() => toggleType(t)} />
                  {t.replaceAll("_", " ")}
                </label>
              ))}
            </div>
            <span className="field-hint">
              Which round (1, 2, ...) a technical interview is doesn't change what you're
              qualified for — the recruiter picks that when they create the request.
            </span>
          </div>

          <div className="field field-span-2">
            <label className="checkbox-row">
              <input type="checkbox" checked={form.active} onChange={(e) => set("active", e.target.checked)} />
              Available for assignment right now
            </label>
          </div>
        </div>

        {error && <p className="field-error" style={{ marginTop: "1rem" }}>{error}</p>}

        <div className="form-actions">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save profile"}
          </button>
        </div>
      </form>
    </div>
  );
}
