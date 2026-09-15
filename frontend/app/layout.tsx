import type { Metadata } from "next";
import { ThemeProvider } from "@/lib/theme";
import { I18nProvider } from "@/lib/i18n";
import { ShellGate } from "@/components/ShellGate";
import "./globals.css";

export const metadata: Metadata = {
  title: "TGStory — tgstory.space",
  description: "Автоматический просмотр и мониторинг Telegram Stories — tgstory.space",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <I18nProvider>
            <ShellGate>{children}</ShellGate>
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
