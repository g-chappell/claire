// lib/experimentSettings.ts

export type PromptContextMode = "structured" | "flat";

export type ExperimentSettings = {
  experimentLabel: string;
  promptContextMode: PromptContextMode;
  useRag: boolean;
};

const STORAGE_KEY = "claire.experimentSettings.v1";

export function loadExperimentSettings(): ExperimentSettings {
  if (typeof window === "undefined") {
    return {
      experimentLabel: "trial1.baseline",
      promptContextMode: "structured",
      useRag: true,
    };
  }

  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return {
      experimentLabel: "trial1.baseline",
      promptContextMode: "structured",
      useRag: true,
    };
  }

  try {
    const parsed = JSON.parse(raw) as Partial<ExperimentSettings>;
    return {
      experimentLabel: parsed.experimentLabel ?? "trial1.baseline",
      promptContextMode:
        parsed.promptContextMode === "flat" ? "flat" : "structured",
      useRag:
        typeof parsed.useRag === "boolean" ? parsed.useRag : true,
    };
  } catch {
    return {
      experimentLabel: "trial1.baseline",
      promptContextMode: "structured",
      useRag: true,
    };
  }
}

export function saveExperimentSettings(settings: ExperimentSettings): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}
