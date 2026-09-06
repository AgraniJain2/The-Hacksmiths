import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { INTERVIEW_TYPES, SENIORITY_LEVELS } from "../lib/constants";
import { IconCheck, IconSparkle } from "../components/icons";
import styles from "./RequestNew.module.css";

const initial = {
  interview_type: INTERVIEW_TYPES[1],
  required_skills: "",
  seniority: "MID",
  panelists_required: 1,
  duration_minutes: 60,
  buffer_minutes_before: 15,
  buffer_minutes_after: 15,
  hiring_manager_email: "",
  candidate_name: "",
  candidate_email: "",
  candidate_timezone: "",
};

export default function RequestNew() {
  const [form, setForm] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [copied, setCopied] = useState(false);

  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = {
        interview_type: form.interview_type,
        required_skills: form.required_skills
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        seniority: form.seniority,
        panelists_required: Number(form.panelists_required),
        duration_minutes: Number(form.duration_minutes),
        buffer_minutes_before: Number(form.buffer_minutes_before),
        buffer_minutes_after: Number(form.buffer_minutes_after),
        hiring_manager_email: form.hiring_manager_email || null,
        candidate_name: form.candidate_name,
        candidate_email: form.candidate_email,
        candidate_timezone: form.candidate_timezone,
      };
      if (body.required_skills.length === 0) {
        throw new Error("Add at least one required skill.");
      }
      const res = await api.createRequest(body);
      setResult(res);
    } catch (err) {
      setError(err.message || "Couldn't create the request.");
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(result.invite_link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API can be denied — the link is still selectable text.
    }
  }

  if (result) {
    return (
      <div className={`animate-in ${styles.wrap}`}>
        <div className={`glass-card ${styles.successCard}`}>
          <IconCheck width={32} height={32} className={styles.successIcon} />
          <h1 className="heading-display" style={{ fontSize: "1.5rem" }}>
            Request created
          </h1>
          <p className="text-secondary" style={{ marginTop: "0.5rem" }}>
            There's no automatic email yet (the Notification Service isn't built) — share this
            invite link with {form.candidate_name || "the candidate"} yourself.
          </p>
          <div className={styles.linkRow}>
            <input className="input" readOnly value={result.invite_link} onFocus={(e) => e.target.select()} />
            <button className="btn btn-outline btn-sm" onClick={copyLink}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <div className={styles.successActions}>
            <Link to={`/requests/${result.request.request_id}`} className="btn btn-primary">
              View request
            </Link>
            <Link to="/requests" className="btn btn-ghost">
              Back to requests
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`animate-in ${styles.wrap}`}>
      <div className={styles.header}>
        <h1 className={`heading-display ${styles.heading}`}>New interview request</h1>
        <p className={styles.subtitle}>
          Describe the round — the panel gets filled automatically once the candidate picks a
          time, no named panelist here.
        </p>
      </div>

      <form className={`glass-card ${styles.card}`} onSubmit={handleSubmit}>
        <p className={styles.sectionLabel}>Round</p>
        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="interview_type">
              Interview type
            </label>
            <select
              id="interview_type"
              className="select"
              value={form.interview_type}
              onChange={(e) => set("interview_type", e.target.value)}
            >
              {INTERVIEW_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="seniority">
              Minimum seniority
            </label>
            <select
              id="seniority"
              className="select"
              value={form.seniority}
              onChange={(e) => set("seniority", e.target.value)}
            >
              {SENIORITY_LEVELS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="field field-span-2">
            <label className="field-label" htmlFor="skills">
              Required skills
            </label>
            <input
              id="skills"
              className="input"
              placeholder="python, system-design, algorithms"
              value={form.required_skills}
              onChange={(e) => set("required_skills", e.target.value)}
            />
            <span className="field-hint">Comma-separated. The panel must cover every one.</span>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="panelists">
              Panelists needed (N)
            </label>
            <input
              id="panelists"
              type="number"
              min={1}
              max={10}
              className="input"
              value={form.panelists_required}
              onChange={(e) => set("panelists_required", e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="hm_email">
              Hiring manager email (optional)
            </label>
            <input
              id="hm_email"
              type="email"
              className="input"
              placeholder="not pooled, just attends"
              value={form.hiring_manager_email}
              onChange={(e) => set("hiring_manager_email", e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="duration">
              Duration (minutes)
            </label>
            <input
              id="duration"
              type="number"
              min={1}
              className="input"
              value={form.duration_minutes}
              onChange={(e) => set("duration_minutes", e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label">Buffer before / after (minutes)</label>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <input
                type="number"
                min={0}
                className="input"
                value={form.buffer_minutes_before}
                onChange={(e) => set("buffer_minutes_before", e.target.value)}
              />
              <input
                type="number"
                min={0}
                className="input"
                value={form.buffer_minutes_after}
                onChange={(e) => set("buffer_minutes_after", e.target.value)}
              />
            </div>
          </div>
        </div>

        <p className={styles.sectionLabel}>Candidate</p>
        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="cand_name">
              Name
            </label>
            <input
              id="cand_name"
              required
              className="input"
              value={form.candidate_name}
              onChange={(e) => set("candidate_name", e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="cand_email">
              Email
            </label>
            <input
              id="cand_email"
              type="email"
              required
              className="input"
              value={form.candidate_email}
              onChange={(e) => set("candidate_email", e.target.value)}
            />
          </div>
          <div className="field field-span-2">
            <label className="field-label" htmlFor="cand_tz">
              Candidate timezone
            </label>
            <input
              id="cand_tz"
              required
              className="input"
              placeholder="Asia/Kolkata"
              value={form.candidate_timezone}
              onChange={(e) => set("candidate_timezone", e.target.value)}
            />
            <span className="field-hint">IANA name — ask the candidate, or use their city's zone.</span>
          </div>
        </div>

        {error && <p className="field-error" style={{ marginTop: "1rem" }}>{error}</p>}

        <div className="form-actions">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            <IconSparkle width={16} height={16} />
            {busy ? "Creating…" : "Create request"}
          </button>
        </div>
      </form>
    </div>
  );
}
