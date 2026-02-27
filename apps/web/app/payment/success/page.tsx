"use client";

import Image from "next/image";
import Link from "next/link";

export default function PaymentSuccessPage() {
  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "2rem" }}>
      <Link href="/" style={{ display: "inline-block", marginBottom: "1.25rem" }} aria-label="So Deepfake Detector home">
        <Image src="/logo.png" alt="So Deepfake Detector" width={180} height={60} />
      </Link>
      <h1 style={{ margin: "0 0 0.75rem 0" }}>Payment successful</h1>
      <p style={{ margin: 0, color: "var(--text-muted)" }}>
        You can now upload your video again to start the analysis.
      </p>
      <div style={{ marginTop: "1.25rem" }}>
        <Link href="/" style={{ color: "var(--accent)", fontWeight: 600 }}>
          ← Back to upload
        </Link>
      </div>
    </div>
  );
}

