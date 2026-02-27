import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Deepfake Detector",
  description: "Analyze a video and get a deepfake likelihood score with confidence and flagged timestamps.",
  icons: {
    icon: [
      { url: "/favicon.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon.png", sizes: "96x96", type: "image/png" },
    ],
    apple: [{ url: "/favicon.png", sizes: "180x180", type: "image/png" }],
  },
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
