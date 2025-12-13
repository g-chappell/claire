// lib/experimentSettings.ts

export type PromptContextMode = "structured" | "features_only" | "minimal";
export type LlmProvider = "anthropic" | "openai";

export type ExperimentSettings = {
  experimentLabel: string;
  promptContextMode: PromptContextMode;
  useRag: boolean;
  llmProvider: LlmProvider;
};

const STORAGE_KEY = "claire.experimentSettings.v1";

export function loadExperimentSettings(): ExperimentSettings {
  if (typeof window === "undefined") {
    return {
      experimentLabel: "trial1.baseline",
      promptContextMode: "structured",
      useRag: true,
      llmProvider: "anthropic",   // default
    };
  }

  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return {
      experimentLabel: "trial1.baseline",
      promptContextMode: "structured",
      useRag: true,
      llmProvider: "anthropic",
    };
  }

  try {
    const parsed = JSON.parse(raw) as Partial<ExperimentSettings> & {
      // for back-compat, allow legacy "flat" string
      promptContextMode?: string;
      llmProvider?: string;
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

    let provider: LlmProvider = "anthropic";
    if (parsed.llmProvider === "openai") {
      provider = "openai";
    } else if (parsed.llmProvider === "anthropic") {
      provider = "anthropic";
    }

    return {
      experimentLabel: parsed.experimentLabel ?? "trial1.baseline",
      promptContextMode: mode,
      useRag: typeof parsed.useRag === "boolean" ? parsed.useRag : true,
      llmProvider: provider,
    };
  } catch {
    return {
      experimentLabel: "trial1.baseline",
      promptContextMode: "structured",
      useRag: true,
      llmProvider: "anthropic",
    };
  }
}

export function saveExperimentSettings(settings: ExperimentSettings): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}
