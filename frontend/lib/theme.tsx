"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

const THEME_KEY = "storywatcher_theme";

type Theme = "dark" | "light";

function initial(): Theme {
  // The app is dark-theme only. Keep persisting the value so the class stays
  // stable across reloads and any legacy "light" value is overwritten.
  return "dark";
}

const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>({
  theme: "dark",
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme] = useState<Theme>(initial);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("dark");
    root.classList.remove("light");
    window.localStorage.setItem(THEME_KEY, "dark");
  }, []);

  const toggle = useCallback(() => {
    // No theme switching: the app is dark-only.
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}