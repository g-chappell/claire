import { useEffect, useMemo, useState } from "react";
import {
  createRun,
  deleteRun,
  getRun,
  listRuns,
  generateVisionSolution,
  getVisionSolution,
  updateVisionSolution,
} from "../lib/api";

import type { RunCreate, RunSummary, RunDetail, VisionSolution } from "../types";

import ChipInput from "../components/ChipInput";
import KeyValueInput from "../components/KeyValueInput";
import LoadingButton from "../components/LoadingButton";
import Badge from "../components/Badge";

export default function PlanManageRun() {
  // ----- create form -----
  const [title, setTitle] = useState("");
  const [reqTitle, setReqTitle] = useState("");
  const [reqDesc, setReqDesc] = useState("");
  const [busyCreate, setBusyCreate] = useState(false);

    // ----- PV/TS gate -----
  const [vs, setVS] = useState<VisionSolution | null>(null);
  const [vsBusy, setVsBusy] = useState(false);
  const [vsMsg, setVsMsg] = useState<string | null>(null);

  const [goals, setGoals] = useState<string[]>([]);
  const [personas, setPersonas] = useState<string[]>([]);
  const [features, setFeatures] = useState<string[]>([]);
  const [stack, setStack] = useState<string[]>([]);
  const [modules, setModules] = useState<string[]>([]);
  const [interfaces, setInterfaces] = useState<Record<string, string>>({});
  const [decisions, setDecisions] = useState<string[]>([]);

  // placeholders that explain how to fill it in
  const runTitlePH = "Short label, e.g. “Onboarding flow – v1”";
  const reqTitlePH = "As a <persona>, I want <capability> so that <benefit>";
  const reqDescPH = "Describe the requirement in a few sentences. You can list constraints or NFRs if helpful.";

  // ----- runs list / selection -----
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | "">("");
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const selected = useMemo(
    () => runs.find(r => r.id === selectedId),
    [runs, selectedId]
  );

  async function refreshRuns(preserveSelection = false) {
  const list = await listRuns();
  setRuns(list);

  if (!preserveSelection) {
    const id = list[0]?.id ?? "";
    setSelectedId(id);

    if (id) {
      const d = await getRun(id);
      setDetail(d);
      await loadVS(id); // fetch PV/TS and hydrate chip editors
    } else {
      // no runs — clear detail and chip editors
      setDetail(null);
      setVS(null);
      setGoals([]);
      setPersonas([]);
      setFeatures([]);
      setStack([]);
      setModules([]);
      setInterfaces({});
      setDecisions([]);
    }
  } else {
    // if current selection vanished, pick first (or clear)
    if (selectedId && !list.some((r) => r.id === selectedId)) {
      const id = list[0]?.id ?? "";
      setSelectedId(id);
      if (id) {
        const d = await getRun(id);
        setDetail(d);
        await loadVS(id);
      } else {
        setDetail(null);
        setVS(null);
        setGoals([]);
        setPersonas([]);
        setFeatures([]);
        setStack([]);
        setModules([]);
        setInterfaces({});
        setDecisions([]);
      }
    }
  }
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
      setVS(null);
      setGoals([]); setPersonas([]); setFeatures([]);
      setStack([]); setModules([]); setInterfaces({}); setDecisions([]);
    }
  }

  useEffect(() => {
    refreshRuns(false).catch(console.error);
  }, []);

  async function onCreate() {
  const payload: RunCreate = {
    title: title.trim() || "(untitled)",
    requirement_title: reqTitle.trim() || "As a user, I want ...",
    requirement_description: reqDesc.trim() || "Describe the requirement…",
    constraints: [],
    priority: "Should",
    non_functionals: [],
  };

  setBusyCreate(true);
  try {
    const created = await createRun(payload);
    // tolerate either shape:
    // - { run_id: string }
    // - { run: { id: string, ... }, manifest, requirement }
    const newId =
      (created as any)?.run_id ??
      (created as any)?.run?.id ??
      (created as any)?.id ??
      "";

    if (!newId) throw new Error("Create returned no run id");

    // force a clean refresh and select the new one
    await refreshRuns(true);
    setSelectedId(newId);
    setDetail(await getRun(newId));
    await loadVS(newId);
  } finally {
    setBusyCreate(false);
  }
}

  async function onSelect(id: string) {
    setSelectedId(id);
    if (!id) { setDetail(null); return; }
    setBusy(true);
    try {
      const d = await getRun(id);
      setDetail(d);
      await loadVS(id);
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!selectedId) return;
    if (!confirm("Delete this run and ALL associated artefacts?")) return;
    setBusy(true);
    try {
      const { deleted } = await deleteRun(selectedId);
      if (deleted) {
        alert("Deleted:\n" + Object.entries(deleted).map(([k,v])=>`• ${k}: ${v}`).join("\n"));
      }
      await refreshRuns(false);
    } finally { setBusy(false); }
  }

  async function onGenerateVS() {
    if (!selectedId) return;
    setVsBusy(true); setVsMsg(null);
    try {
      const data = await generateVisionSolution(selectedId);
      setVS(data);
      setGoals(data.product_vision.goals ?? []);
      setPersonas(data.product_vision.personas ?? []);
      setFeatures(data.product_vision.features ?? []);
      setStack(data.technical_solution.stack ?? []);
      setModules(data.technical_solution.modules ?? []);
      setInterfaces(data.technical_solution.interfaces ?? {});
      setDecisions(data.technical_solution.decisions ?? []);
      setDetail(await getRun(selectedId)); // refresh badge (status=draft)
      setVsMsg("Generated Product Vision & Technical Solution.");
    } catch (e:any) {
      setVsMsg(`Error: ${e.message ?? e}`);
    } finally {
      setVsBusy(false);
    }
  }

  async function onReloadVS() {
    if (!selectedId) return;
    setVsBusy(true);
    try {
      await loadVS(selectedId);
      setVsMsg("Reloaded.");
    } finally {
      setVsBusy(false);
    }
  }

  async function onRegenerateVS() {
    if (!selectedId) return;
    if (
      goals.length || personas.length || features.length ||
      stack.length || modules.length || decisions.length ||
      Object.keys(interfaces).length
    ) {
      const ok = confirm("You have unsaved edits. Re-generate will overwrite. Continue?");
      if (!ok) return;
    }
    setVsBusy(true); setVsMsg(null);
    try {
      const data = await generateVisionSolution(selectedId);
      setVS(data);
      setGoals(data.product_vision.goals ?? []);
      setPersonas(data.product_vision.personas ?? []);
      setFeatures(data.product_vision.features ?? []);
      setStack(data.technical_solution.stack ?? []);
      setModules(data.technical_solution.modules ?? []);
      setInterfaces(data.technical_solution.interfaces ?? {});
      setDecisions(data.technical_solution.decisions ?? []);
      setVsMsg("Re-generated PV/TS.");
    } catch (e:any) {
      setVsMsg(e.message ?? "Failed to re-generate PV/TS");
    } finally {
      setVsBusy(false);
    }
  }

  async function onSaveVS() {
    if (!selectedId) return;
    setVsBusy(true); setVsMsg(null);
    try {
      const payload = {
        product_vision: {
          id: vs?.product_vision.id ?? "PV",
          goals, personas, features,
        },
        technical_solution: {
          id: vs?.technical_solution.id ?? "TS",
          stack, modules, interfaces, decisions,
        },
      };
      const updated = await updateVisionSolution(selectedId, payload);
      setVS(updated);
      setDetail(await getRun(selectedId)); // keep badge accurate
      setVsMsg("Saved.");
    } catch (e:any) {
      setVsMsg(`Error: ${e.message ?? e}`);
    } finally {
      setVsBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* ===== Create Run ===== */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="text-lg font-semibold mb-4">Create Run</h2>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3">
          <div>
            <label className="block text-sm mb-1 opacity-80">Run title</label>
            <input
              className="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
              placeholder={runTitlePH}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm mb-1 opacity-80">Requirement title</label>
            <input
              className="w-full rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
              placeholder={reqTitlePH}
              value={reqTitle}
              onChange={(e) => setReqTitle(e.target.value)}
            />
          </div>
        </div>

        <div className="mb-4">
          <label className="block text-sm mb-1 opacity-80">Requirement description</label>
          <textarea
            className="w-full min-h-[120px] rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
            placeholder={reqDescPH}
            value={reqDesc}
            onChange={(e) => setReqDesc(e.target.value)}
          />
        </div>

        <button
          onClick={onCreate}
          disabled={busyCreate}
          className="px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
        >
          {busyCreate ? "Creating…" : "Create Run"}
        </button>
      </section>

      {/* ===== Select / Manage existing runs ===== */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="text-lg font-semibold mb-4">Manage Existing Runs</h2>

        <div className="flex items-center gap-2 mb-4">
          <select
            className="min-w-[360px] rounded-md bg-slate-800 border border-slate-700 px-3 py-2"
            value={selectedId}
            onChange={(e) => onSelect(e.target.value)}
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {(r.title || "(untitled)")} — {r.id.slice(0, 8)} — {r.status}
              </option>
            ))}
            {!runs.length && <option value="">(no runs found)</option>}
          </select>

          <button
            onClick={onDelete}
            disabled={!selectedId || busy}
            className="px-3 py-2 rounded-md bg-red-600 hover:bg-red-500 disabled:opacity-50"
          >
            Delete
          </button>
        </div>

        {/* Details Panel */}
        {selected && detail ? (
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 space-y-4">
            <div>
              <h3 className="font-semibold">Run</h3>
              <div className="text-sm opacity-80">
                <div>ID: {detail.run.id}</div>
                <div>Status: {detail.run.status}</div>
                <div>Started: {detail.run.started_at ?? "—"}</div>
                <div>Finished: {detail.run.finished_at ?? "—"}</div>
              </div>
            </div>

            {/* ===== Product Vision & Technical Solution (Stage Gate) ===== */}
<section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
  <div className="flex items-center justify-between mb-3">
    <h2 className="text-lg font-semibold">Product Vision & Technical Solution</h2>
    <Badge tone={detail?.manifest?.data?.vision_solution_status === "approved" ? "emerald" : "amber"}>
      Gate: {detail?.manifest?.data?.vision_solution_status ?? "—"}
    </Badge>
  </div>

  <div className="flex items-center gap-2 mb-4">
    <LoadingButton
      className="bg-emerald-600 hover:bg-emerald-500"
      loading={vsBusy}
      disabled={!selectedId}
      onClick={onGenerateVS}
    >
      Generate
    </LoadingButton>
    <LoadingButton
      className="bg-slate-700 hover:bg-slate-600"
      loading={vsBusy}
      disabled={!selectedId}
      onClick={onReloadVS}
    >
      Reload
    </LoadingButton>
    <LoadingButton
      className="bg-amber-600 hover:bg-amber-500"
      loading={vsBusy}
      disabled={!selectedId}
      onClick={onRegenerateVS}
    >
      Re-generate
    </LoadingButton>
    <div className="text-sm opacity-80">{vsMsg}</div>
  </div>

  {vs ? (
    <div className="grid md:grid-cols-2 gap-4">
      <div className="border border-slate-800 rounded-lg p-3">
        <h3 className="font-semibold mb-3">Product Vision</h3>
        <ChipInput label="Goals" value={goals} onChange={setGoals} />
        <div className="h-3" />
        <ChipInput label="Personas" value={personas} onChange={setPersonas} />
        <div className="h-3" />
        <ChipInput label="Features" value={features} onChange={setFeatures} />
      </div>

      <div className="border border-slate-800 rounded-lg p-3">
        <h3 className="font-semibold mb-3">Technical Solution</h3>
        <ChipInput label="Stack" value={stack} onChange={setStack} />
        <div className="h-3" />
        <ChipInput label="Modules" value={modules} onChange={setModules} />
        <div className="h-3" />
        <KeyValueInput label="Interfaces (k:v, comma-separated)" value={interfaces} onChange={setInterfaces} />
        <div className="h-3" />
        <ChipInput label="Decisions" value={decisions} onChange={setDecisions} />
      </div>
    </div>
  ) : (
    <div className="text-sm opacity-70">
      No PV/TS yet — click <b>Generate</b> to draft the Product Vision & Technical Solution.
    </div>
  )}

  <div className="mt-4">
    <LoadingButton
      className="bg-indigo-600 hover:bg-indigo-500"
      loading={vsBusy}
      disabled={!selectedId || !vs}
      onClick={onSaveVS}
    >
      Save
    </LoadingButton>
  </div>
</section>

            <div>
              <h3 className="font-semibold">Requirement</h3>
              {detail.requirement ? (
                <div className="text-sm opacity-80 space-y-1">
                  <div><span className="opacity-70">Title: </span>{detail.requirement.title}</div>
                  <div className="opacity-70">Description:</div>
                  <pre className="whitespace-pre-wrap bg-slate-800 rounded p-2 border border-slate-700">
                    {detail.requirement.description}
                  </pre>
                </div>
              ) : (
                <div className="text-sm opacity-60">No requirement persisted.</div>
              )}
            </div>
          </div>
        ) : (
          <div className="text-sm opacity-60">Select a run to view details.</div>
        )}
      </section>
    </div>
  );
}
