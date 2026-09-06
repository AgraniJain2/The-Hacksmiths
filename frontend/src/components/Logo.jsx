import styles from "./Logo.module.css";

export default function Logo({ size = "md" }) {
  return (
    <span className={`${styles.logo} ${styles[size]}`}>
      <svg viewBox="0 0 32 32" className={styles.mark} aria-hidden="true">
        <defs>
          <linearGradient id="workhire-mark" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--accent)" />
            <stop offset="1" stopColor="var(--accent-2)" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="9" fill="url(#workhire-mark)" />
        <path
          d="M9 21V11.5l7 5.2 7-5.2V21"
          stroke="white"
          strokeWidth="2.2"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className={styles.word}>
        Work<span className="text-gradient">Hire</span>
      </span>
    </span>
  );
}
