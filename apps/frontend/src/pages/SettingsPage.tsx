import { useEffect, useState } from "react";
import {
  loadExperimentSettings,
  saveExperimentSettings,
  type ExperimentSettings,
} from "../lib/experimentSettings";

export default function SettingsPage() {
  const [settings, setSettings] = useState<ExperimentSettings>(() =>
    loadExperimentSettings()
  );
  

  useEffect(() => {
    saveExperimentSettings(settings);
  }, [settings]);

  const update = (patch: Partial<ExperimentSettings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  };

  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900">
          Experiment settings
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Configure the knobs CLAIRE uses when planning and executing a Run.
          These values are snapshotted into each new Run&apos;s manifest at
          creation time and used for your trials and ablations.
        </p>
      </header>

      {/* Experiment label */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">
            Trial / experiment label
          </h2>
          <p className="text-xs text-slate-500">
            Tag runs for your study, e.g.{" "}
            <code className="font-mono text-[11px] bg-slate-100 px-1 rounded">
              trial1.baseline
            </code>
            ,{" "}
            <code className="font-mono text-[11px] bg-slate-100 px-1 rounded">
              trial3.best
            </code>
            ,{" "}
            <code className="font-mono text-[11px] bg-slate-100 px-1 rounded">
              ablation.rag_off
            </code>
            .
          </p>
        </div>
        <input
          type="text"
          className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
          value={settings.experimentLabel}
          onChange={(e) => update({ experimentLabel: e.target.value })}
          placeholder="trial1.baseline"
        />
      </section>

      {/* Prompt context mode */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-3">
        <h2 className="text-sm font-semibold text-slate-800">
          Prompt context mode
        </h2>
        <p className="text-xs text-slate-500 mb-1">
          Controls how much structured context the planning team sees and how
          prescriptive the requirements prompt is.
        </p>

        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-stretch">
          {/* Structured */}
          <button
            type="button"
            onClick={() => update({ promptContextMode: "structured" })}
            className={`flex-1 rounded-md border px-3 py-2 text-left text-sm transition
              ${
                settings.promptContextMode === "structured"
                  ? "border-indigo-500 bg-indigo-50 text-indigo-900 shadow-sm"
                  : "border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-800"
              }`}
          >
            <div className="font-medium">Structured</div>
            <div className="mt-0.5 text-xs text-slate-600">
              Full context (vision, solution, decisions, feedback) +
              rich, prescriptive RA prompt.
            </div>
          </button>

          {/* Features only */}
          <button
            type="button"
            onClick={() => update({ promptContextMode: "features_only" })}
            className={`flex-1 rounded-md border px-3 py-2 text-left text-sm transition
              ${
                settings.promptContextMode === "features_only"
                  ? "border-indigo-500 bg-indigo-50 text-indigo-900 shadow-sm"
                  : "border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-800"
              }`}
          >
            <div className="font-medium">Features only</div>
            <div className="mt-0.5 text-xs text-slate-600">
              Full RA prompt, but only the feature list is injected
              (no architecture / feedback context).
            </div>
          </button>

          {/* Minimal */}
          <button
            type="button"
            onClick={() => update({ promptContextMode: "minimal" })}
            className={`flex-1 rounded-md border px-3 py-2 text-left text-sm transition
              ${
                settings.promptContextMode === "minimal"
                  ? "border-indigo-500 bg-indigo-50 text-indigo-900 shadow-sm"
                  : "border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-800"
              }`}
          >
            <div className="font-medium">Minimal</div>
            <div className="mt-0.5 text-xs text-slate-600">
              Feature-only context plus a simpler RA prompt for
              ablation of context engineering.
            </div>
          </button>
        </div>
      </section>

      {/* RAG toggle */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-3">
        <h2 className="text-sm font-semibold text-slate-800">
          Retrieval (RAG) usage
        </h2>
        <p className="text-xs text-slate-500">
          Master switch for RAG in planning. When disabled, planning uses only
          local run artefacts.
        </p>

        <label className="mt-1 inline-flex items-center gap-2 cursor-pointer select-none">
          <div
            className={`relative inline-flex h-5 w-9 items-center rounded-full border transition
              ${
                settings.useRag
                  ? "bg-indigo-500 border-indigo-500"
                  : "bg-slate-200 border-slate-300"
              }`}
          >
            <span
              className={`inline-block h-4 w-4 rounded-full bg-white shadow transform transition
                ${settings.useRag ? "translate-x-4" : "translate-x-0"}`}
            />
          </div>
          <input
            type="checkbox"
            className="sr-only"
            checked={settings.useRag}
            onChange={(e) => update({ useRag: e.target.checked })}
          />
          <span className="text-sm text-slate-800">
            {settings.useRag ? "RAG enabled" : "RAG disabled"}
          </span>
        </label>
      </section>

       {/* LLM provider */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-3">
        <h2 className="text-sm font-semibold text-slate-800">
          LLM provider
        </h2>
        <p className="text-xs text-slate-500">
          Choose which LLM backend CLAIRE should use for planning and execution.
          Ensure the matching API key is configured in the backend environment.
        </p>

        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-stretch mt-1">
          {/* Anthropic */}
          <button
            type="button"
            onClick={() => update({ llmProvider: "anthropic" })}
            className={`flex-1 rounded-md border px-3 py-2 text-left text-sm transition
              ${
                settings.llmProvider === "anthropic"
                  ? "border-indigo-500 bg-indigo-50 text-indigo-900 shadow-sm"
                  : "border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-800"
              }`}
          >
            <div className="font-medium">Anthropic (Claude)</div>
            <div className="mt-0.5 text-xs text-slate-600">
              Use Claude Sonnet for planning and coding.
            </div>
          </button>

          {/* OpenAI */}
          <button
            type="button"
            onClick={() => update({ llmProvider: "openai" })}
            className={`flex-1 rounded-md border px-3 py-2 text-left text-sm transition
              ${
                settings.llmProvider === "openai"
                  ? "border-indigo-500 bg-indigo-50 text-indigo-900 shadow-sm"
                  : "border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-800"
              }`}
          >
            <div className="font-medium">OpenAI</div>
            <div className="mt-0.5 text-xs text-slate-600">
              Use OpenAI models (e.g. GPT-4.x) instead.
            </div>
          </button>
        </div>
      </section>

    </div>
  );
}
