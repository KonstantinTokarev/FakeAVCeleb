"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import styles from "./admin.module.css";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface JobRow {
  id: string;
  status: string;
  input_type: string;
  created_at: string | null;
  error_code: string | null;
  error_message: string | null;
  result_id: string | null;
}

export default function AdminPage() {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/admin/jobs?limit=50`);
        if (res.ok) {
          const data = await res.json();
          setJobs(data.jobs || []);
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className={styles.wrapper}>
      <h1 className={styles.title}>Admin — Job logs</h1>
      <Link href="/" className={styles.link}>← Back to analyzer</Link>
      {loading ? (
        <p className={styles.muted}>Loading…</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Status</th>
                <th>Type</th>
                <th>Created</th>
                <th>Error</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td className={styles.id}>{j.id.slice(0, 8)}…</td>
                  <td><span className={(styles as Record<string, string>)[`status_${j.status}`] ?? styles.status}>{j.status}</span></td>
                  <td>{j.input_type}</td>
                  <td className={styles.muted}>{j.created_at ? new Date(j.created_at).toLocaleString() : "—"}</td>
                  <td className={styles.muted}>{j.error_code || j.error_message || "—"}</td>
                  <td>
                    {j.result_id && (
                      <Link href={`/jobs/${j.id}/result`} className={styles.link}>Result</Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
