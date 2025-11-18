import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type PersonalizationSettings = {
  // Whether the agent should remember long-term context across sessions
  rememberLongTermContext: boolean;
  // Optional freeform long-term context for the AI to learn from
  longTermContext: string;
  // Tone/style of responses
  responseTone: "professional" | "friendly" | "concise" | "detailed";
  // Domain focus to bias suggestions
  domainFocus: "sales" | "customer_service" | "marketing" | "management" | "general";
  // Whether to show agent internal activity (thoughts/tools)
  showAgentInternals: boolean;
};

export const defaultPersonalizationSettings: PersonalizationSettings = {
  rememberLongTermContext: true,
  longTermContext: "",
  responseTone: "professional",
  domainFocus: "general",
  showAgentInternals: true,
};

const STORAGE_KEY = "personalization-settings:v1";

type PersonalizationContextValue = {
  settings: PersonalizationSettings;
  updateSettings: (partial: Partial<PersonalizationSettings>) => void;
  resetSettings: () => void;
};

const PersonalizationContext = createContext<PersonalizationContextValue | undefined>(undefined);

export const usePersonalization = (): PersonalizationContextValue => {
  const ctx = useContext(PersonalizationContext);
  if (!ctx) {
    throw new Error("usePersonalization must be used within PersonalizationProvider");
  }
  return ctx;
};

function safeParse(json: string | null): Partial<PersonalizationSettings> | null {
  if (!json) return null;
  try {
    const parsed = JSON.parse(json);
    if (typeof parsed === "object" && parsed !== null) {
      // Return as partial; we'll merge with defaults to ensure new fields
      return parsed as Partial<PersonalizationSettings>;
    }
  } catch (_err) {
    // ignore and fall through to default
  }
  return null;
}

export const PersonalizationProvider = ({ children }: { children: React.ReactNode }) => {
  const [settings, setSettings] = useState<PersonalizationSettings>(() => {
    const fromStorage = safeParse(localStorage.getItem(STORAGE_KEY));
    return { ...defaultPersonalizationSettings, ...(fromStorage ?? {}) };
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  }, [settings]);

  const updateSettings = (partial: Partial<PersonalizationSettings>) => {
    setSettings((prev) => ({ ...prev, ...partial }));
  };

  const resetSettings = () => {
    setSettings(defaultPersonalizationSettings);
  };

  const value = useMemo<PersonalizationContextValue>(() => ({ settings, updateSettings, resetSettings }), [settings]);

  return <PersonalizationContext.Provider value={value}>{children}</PersonalizationContext.Provider>;
};
