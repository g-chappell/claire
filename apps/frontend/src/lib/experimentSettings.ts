// lib/experimentSettings.ts

export type PromptContextMode = "structured" | "features_only" | "minimal";

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
    const parsed = JSON.parse(raw) as Partial<ExperimentSettings> & {
      // for back-compat, allow legacy "flat" string
      promptContextMode?: string;
    };

    let mode: PromptContextMode = "structured";
    const rawMode = parsed.promptContextMode as string | undefined;

    if (rawMode === "flat") {
      // legacy value → new semantics
      mode = "features_only";
    } else if (
      rawMode === "structured" ||
      rawMode === "features_only" ||
      rawMode === "minimal"
    ) {
      mode = rawMode as PromptContextMode;
    }

    return {
      experimentLabel: parsed.experimentLabel ?? "trial1.baseline",
      promptContextMode: mode,
      useRag: typeof parsed.useRag === "boolean" ? parsed.useRag : true,
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
