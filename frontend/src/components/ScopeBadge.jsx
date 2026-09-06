import { IconCheck, IconLock } from "./icons";

/**
 * One Google scope's granted/missing state as a pill. `scope` is the short
 * name used by the backend's require_google_scope() ("calendar" | "gmail"),
 * `label` is what a human sees.
 */
export default function ScopeBadge({ label, granted }) {
  const cls = granted ? "pill pill-success" : "pill pill-neutral";
  return (
    <span className={cls}>
      {granted ? <IconCheck width={12} height={12} /> : <IconLock width={12} height={12} />}
      {label}
    </span>
  );
}
