"use client";

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import { api } from "@/lib/api";
import ru from "@/lib/translations/ru";
import en from "@/lib/translations/en";

export type Lang = "ru" | "en";

const translations: Record<Lang, typeof ru> = { ru, en };

// Pluralization helper
type PluralForms = { one: string; few: string; many: string };

function pluralize(lang: Lang, forms: PluralForms, n: number): string {
  const abs = Math.abs(n) % 100;
  const lastDigit = abs % 10;
  if (lang === "ru") {
    if (abs > 10 && abs < 20) return forms.many;
    if (lastDigit > 1 && lastDigit < 5) return forms.few;
    if (lastDigit === 1) return forms.one;
    return forms.many;
  }
  // English: just use singular/plural
  return n === 1 ? forms.one : forms.few;
}

// Interpolation: replaces {key} and handles plural {one|few|many} forms
function interpolate(
  template: string,
  vars: Record<string, string | number>,
  lang: Lang
): string {
  return template.replace(/\{(\w+)(?:\|(\w+:\{?\w+\}?)*)\}/g, (match, key, _rest) => {
    // Handle plural forms like {one:story|few:stories|many:stories}
    if (match.includes(":")) {
      const parts = match.slice(1, -1).split("|");
      const forms: PluralForms = { one: "", few: "", many: "" };
      const numKey = parts.find((p: string) => /^\d+$/.test(p.split(":")[0]))?.split(":")[0];
      for (const part of parts) {
        const [form, text] = part.split(":");
        if (form === "one") forms.one = text;
        else if (form === "few") forms.few = text;
        else if (form === "many") forms.many = text;
      }
      const n = numKey ? Number(vars[numKey]) : 0;
      return pluralize(lang, forms, n);
    }
    const val = vars[key];
    return val !== undefined ? String(val) : match;
  });
}

type I18nContextValue = {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (path: string, vars?: Record<string, string | number>) => string;
};

const I18nContext = createContext<I18nContextValue>({
  lang: "ru",
  setLang: () => {},
  t: (path) => path,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("ru");

  // Load saved language on mount + listen for changes
  useEffect(() => {
    const readLang = () => {
      try {
        const saved = localStorage.getItem("storywatcher_lang") as Lang | null;
        if (saved && (saved === "ru" || saved === "en")) {
          setLangState(saved);
        } else {
          api.get<Record<string, Record<string, unknown>>>("/settings").then((d) => {
            const apiLang = d?.general?.language;
            if (apiLang === "en" || apiLang === "ru") {
              setLangState(apiLang);
              localStorage.setItem("storywatcher_lang", apiLang);
            }
          }).catch(() => {});
        }
      } catch {}
    };
    readLang();
    // Listen for language changes from Settings page
    window.addEventListener("storywatcher:lang-changed", readLang);
    return () => window.removeEventListener("storywatcher:lang-changed", readLang);
  }, []);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    localStorage.setItem("storywatcher_lang", l);
    // Also update the API setting
    api.get<Record<string, Record<string, unknown>>>("/settings").then((d) => {
      if (d) {
        d.general = { ...d.general, language: l };
        api.put("/settings", d).catch(() => {});
      }
    }).catch(() => {});
  }, []);

  const t = useCallback(
    (path: string, vars?: Record<string, string | number>): string => {
      const dict = translations[lang];
      const keys = path.split(".");
      let val: unknown = dict;
      for (const k of keys) {
        if (val && typeof val === "object") {
          val = (val as Record<string, unknown>)[k];
        } else {
          return path;
        }
      }
      if (typeof val !== "string") return path;
      return vars ? interpolate(val, vars, lang) : val;
    },
    [lang]
  );

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useTranslation() {
  return useContext(I18nContext);
}

// Locale-aware date formatting
export function useLocale(): string {
  const { lang } = useTranslation();
  return lang === "ru" ? "ru-RU" : "en-US";
}
