import { useEffect, useState, type ReactNode } from "react";
import RunPicker from "../components/RunPicker";
import {
  getRun,
  generateVisionSolution,
  getVisionSolution,
  updateVisionSolution,
} from "../lib/api";
import type { RunDetail, VisionSolution } from "../types";
import ChipInput from "../components/ChipInput";
import KeyValueInput from "../components/KeyValueInput";
import LoadingButton from "../components/LoadingButton";
import Badge from "../components/Badge";

// Reusable collapsible section
function CollapsibleSection({
  title,
  children,
  defaultOpen = true,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-left"
      >
        <span className="font-semibold">{title}</span>
        <span className="text-slate-400 text-xl leading-none">{open ? "−" : "+"}</span>
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </section>
  );
}

export default function PlanManageRun() {
  // selected run
  const [runId, setRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [busy, setBusy] = useState(false);

  // PV/TS
  const [vs, setVS] = useState<VisionSolution | null>(null);
  const [vsBusy, setVsBusy] = useState(false);
  const [vsMsg, setVsMsg] = useState<string | null>(null);

  // editors
  const [goals, setGoals] = useState<string[]>([]);
  const [personas, setPersonas] = useState<string[]>([]);
  const [features, setFeatures] = useState<string[]>([]);
  const [stack, setStack] = useState<string[]>([]);
  const [modules, setModules] = useState<string[]>([]);
  const [interfaces, setInterfaces] = useState<Record<string, string>>({});
  const [decisions, setDecisions] = useState<string[]>([]);

  function clearEditors() {
    setVS(null);
    setGoals([]);
    setPersonas([]);
    setFeatures([]);
    setStack([]);
    setModules([]);
    setInterfaces({});
    setDecisions([]);
    setVsMsg(null);
  }

  async function loadVS(id: string) {
    try {
      const data = await getVisionSolution(id);
      setVS(data);
      setGoals(data.product_vision.goals ?? []);
      setPersonas(data.product_vision.personas ?? []);
      setFeatures(data.product_vision.features ?? []);
      setStack(data.technical_solution.stack ?? []);
      setModules(data.technical_solution.modules ?? []);
      setInterfaces(data.technical_solution.interfaces ?? {});
      setDecisions(data.technical_solution.decisions ?? []);
      setVsMsg(null);
    } catch {
      clearEditors();
    }
  }

  // when run changes, load detail + PV/TS
  useEffect(() => {
    if (!runId) {
      setDetail(null);
      clearEditors();
      return;
    }
    setBusy(true);
    (async () => {
      const d = await getRun(runId);
      setDetail(d);
      await loadVS(runId);
    })().finally(() => setBusy(false));
  }, [runId]);

  const hasUnsavedEdits =
    goals.length ||
    personas.length ||
    features.length ||
    stack.length ||
    modules.length ||
    decisions.length ||
    Object.keys(interfaces).length;

  async function onGenerateVS() {
    if (!runId) return;
    // One button only: confirm if user has edits that could be overwritten
    if (vs && hasUnsavedEdits) {
      const ok = confirm(
        "You have unsaved edits to Product Vision/Technical Solution. Generating will overwrite the current draft. Continue?"
      );
      if (!ok) return;
    }
    setVsBusy(true);
    setVsMsg(null);
    try {
      const data = await generateVisionSolution(runId);
      setVS(data);
      setGoals(data.product_vision.goals ?? []);
      setPersonas(data.product_vision.personas ?? []);
      setFeatures(data.product_vision.features ?? []);
      setStack(data.technical_solution.stack ?? []);
      setModules(data.technical_solution.modules ?? []);
      setInterfaces(data.technical_solution.interfaces ?? {});
      setDecisions(data.technical_solution.decisions ?? []);
      setDetail(await getRun(runId)); // refresh gate/status
      setVsMsg("Generated Product Vision & Technical Solution.");
    } catch (e: any) {
      setVsMsg(`Error: ${e.message ?? e}`);
    } finally {
      setVsBusy(false);
    }
  }

  async function onReloadVS() {
    if (!runId) return;
    setVsBusy(true);
    try {
      await loadVS(runId);
      setVsMsg("Reloaded.");
    } finally {
      setVsBusy(false);
    }
  }

  async function onSaveVS() {
    if (!runId || !vs) return;
    setVsBusy(true);
    setVsMsg(null);
    try {
      const payload = {
        product_vision: { id: vs.product_vision.id ?? "PV", goals, personas, features },
        technical_solution: { id: vs.technical_solution.id ?? "TS", stack, modules, interfaces, decisions },
      };
      const updated = await updateVisionSolution(runId, payload);
      setVS(updated);
      setDetail(await getRun(runId));
      setVsMsg("Saved.");
    } catch (e: any) {
      setVsMsg(`Error: ${e.message ?? e}`);
    } finally {
      setVsBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Manage Run</h1>

      {/* Toolbar: picker + actions */}
      <div className="flex flex-wrap items-center gap-3">
        <RunPicker value={runId} onChange={setRunId} />
        {detail && (
          <Badge tone={detail?.manifest?.data?.vision_solution_status === "approved" ? "emerald" : "amber"}>
            Gate: {detail?.manifest?.data?.vision_solution_status ?? "—"}
          </Badge>
        )}
        <LoadingButton
          className="bg-emerald-600 hover:bg-emerald-500"
          loading={vsBusy}
          disabled={!runId}
          onClick={onGenerateVS}
        >
          Generate
        </LoadingButton>
        <LoadingButton
          className="bg-slate-700 hover:bg-slate-600"
          loading={vsBusy}
          disabled={!runId}
          onClick={onReloadVS}
        >
          Reload
        </LoadingButton>
        <LoadingButton
          className="bg-indigo-600 hover:bg-indigo-500"
          loading={vsBusy}
          disabled={!runId || !vs}
          onClick={onSaveVS}
        >
          Save
        </LoadingButton>
        {busy && <span className="text-sm opacity-60">Loading…</span>}
        {vsMsg && <span className="text-sm opacity-80">{vsMsg}</span>}
      </div>

      {runId && detail ? (
        <div className="space-y-4">
          {/* 1) Requirement */}
          <CollapsibleSection title="Requirement" defaultOpen>
            {detail.requirement ? (
              <div className="text-sm opacity-80 space-y-1">
                <div>
                  <span className="opacity-70">Title: </span>
                  {detail.requirement.title}
                </div>
                <div className="opacity-70">Description:</div>
                <pre className="whitespace-pre-wrap bg-slate-800 rounded p-2 border border-slate-700">
                  {detail.requirement.description}
                </pre>
              </div>
            ) : (
              <div className="text-sm opacity-60">No requirement persisted.</div>
            )}
          </CollapsibleSection>

          {/* 2) Product Vision */}
          <CollapsibleSection title="Product Vision" defaultOpen>
            <div className="border border-slate-800 rounded-lg p-3">
              <ChipInput label="Goals" value={goals} onChange={setGoals} />
              <div className="h-3" />
              <ChipInput label="Personas" value={personas} onChange={setPersonas} />
              <div className="h-3" />
              <ChipInput label="Features" value={features} onChange={setFeatures} />
            </div>
          </CollapsibleSection>

          {/* 3) Technical Solution */}
          <CollapsibleSection title="Technical Solution" defaultOpen>
            <div className="border border-slate-800 rounded-lg p-3">
              <ChipInput label="Stack" value={stack} onChange={setStack} />
              <div className="h-3" />
              <ChipInput label="Modules" value={modules} onChange={setModules} />
              <div className="h-3" />
              <KeyValueInput label="Interfaces (k:v, comma-separated)" value={interfaces} onChange={setInterfaces} />
              <div className="h-3" />
              <ChipInput label="Decisions" value={decisions} onChange={setDecisions} />
            </div>
          </CollapsibleSection>
        </div>
      ) : (
        <div className="text-sm opacity-60">Select a run to view details.</div>
      )}
    </div>
  );
}
