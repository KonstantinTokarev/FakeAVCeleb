import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Deepfake Detector",
  description: "Analyze a video and get a deepfake likelihood score with confidence and flagged timestamps.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
