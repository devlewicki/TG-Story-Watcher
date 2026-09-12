import type { Metadata } from "next";
import AdminLayout from "@/components/admin/AdminShell";

export const metadata: Metadata = {
  title: "Admin — StoryWatcher",
};

export default function AdminRootLayout({ children }: { children: React.ReactNode }) {
  return <AdminLayout>{children}</AdminLayout>;
}
