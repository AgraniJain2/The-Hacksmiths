import styles from "./BackgroundFX.module.css";

/**
 * Decorative, non-interactive backdrop: a faint grid + two slow-floating
 * gradient blobs. Mount once per full-bleed page (Login, NotFound) — don't
 * stack multiple instances. Purely aria-hidden.
 */
export default function BackgroundFX() {
  return (
    <div className={styles.wrap} aria-hidden="true">
      <div className={styles.grid} />
      <div className={`${styles.blob} ${styles.blobOne}`} />
      <div className={`${styles.blob} ${styles.blobTwo}`} />
    </div>
  );
}
