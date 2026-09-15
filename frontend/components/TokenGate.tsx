"use client";
import { LandingPage } from "@/components/LandingPage";

export function TokenGateContent({ onSaved }: { onSaved: () => void }) {
  return <LandingPage onAuth={onSaved} />;
}
