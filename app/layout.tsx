import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Prime Technical Live Scanner",
  description: "Live BUY/SELL confirmed scanner dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
