import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Edge Memory Dashboard",
  description: "Offline-first edge memory + cloud sync on Qdrant Edge",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
