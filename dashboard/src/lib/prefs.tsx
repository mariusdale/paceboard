/**
 * Client-only display preferences: appearance and whether technical labels
 * (CTL, ATL, TSB, HRV…) show alongside their plain-language names.
 *
 * Both are presentation choices with no effect on stored data or computed
 * metrics, so — unlike units or the backfill window — they live in
 * localStorage rather than round-tripping through /settings.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Appearance = "light" | "dark" | "auto";

const THEME_KEY = "paceboard:appearance";
const JARGON_KEY = "paceboard:jargon";

interface PrefsValue {
  appearance: Appearance;
  setAppearance: (value: Appearance) => void;
  jargon: boolean;
  setJargon: (value: boolean) => void;
}

const PrefsContext = createContext<PrefsValue | null>(null);

function readAppearance(): Appearance {
  const stored = localStorage.getItem(THEME_KEY);
  return stored === "light" || stored === "dark" || stored === "auto" ? stored : "auto";
}

function readJargon(): boolean {
  const stored = localStorage.getItem(JARGON_KEY);
  return stored === null ? true : stored === "1";
}

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearanceState] = useState<Appearance>(readAppearance);
  const [jargon, setJargonState] = useState<boolean>(readJargon);

  useEffect(() => {
    const root = document.documentElement;
    if (appearance === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", appearance);
  }, [appearance]);

  const setAppearance = useCallback((value: Appearance) => {
    localStorage.setItem(THEME_KEY, value);
    setAppearanceState(value);
  }, []);
  const setJargon = useCallback((value: boolean) => {
    localStorage.setItem(JARGON_KEY, value ? "1" : "0");
    setJargonState(value);
  }, []);

  const value = useMemo(
    () => ({ appearance, setAppearance, jargon, setJargon }),
    [appearance, setAppearance, jargon, setJargon],
  );

  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): PrefsValue {
  const ctx = useContext(PrefsContext);
  if (!ctx) throw new Error("usePrefs must be used within PrefsProvider");
  return ctx;
}

/** "Base" or "Base (CTL)", depending on the jargon preference. */
export function jargonLabel(plain: string, technical: string, jargon: boolean): string {
  return jargon ? `${plain} (${technical})` : plain;
}
