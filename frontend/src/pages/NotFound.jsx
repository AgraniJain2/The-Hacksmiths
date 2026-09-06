import { Link } from "react-router-dom";
import BackgroundFX from "../components/BackgroundFX";
import styles from "./NotFound.module.css";

export default function NotFound() {
  return (
    <div className={styles.page}>
      <BackgroundFX />
      <div className="animate-in">
        <p className={styles.code}>404</p>
        <h1 className={`heading-display ${styles.heading}`}>This page doesn't exist yet</h1>
        <Link to="/dashboard" className="btn btn-primary">
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}
