import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nova Clip — AI Video Studio",
  description: "Generate, arrange, and export cinematic AI video sequences.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}

