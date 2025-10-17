import { useEffect, useMemo, useState } from "react";
import RunPicker from "../components/RunPicker";
import { loadPlan } from "../lib/api";
import type { PlanBundle, Epic, Story } from "../types";
import Collapsible from "../components/Collapsible";

export default function PlanView() {
  const [runId, setRunId] = useState<string | null>(null);
  const [bundle, setBundle] = useState<PlanBundle | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { setBundle(null); setErr(null); }, [runId]);

  async function fetchPlan() {
    if (!runId) return;
    setBusy(true); setErr(null);
    try { setBundle(await loadPlan(runId)); }
    catch (e:any) { setErr(e.message ?? String(e)); }
    finally { setBusy(false); }
  }

  const storiesByEpic = useMemo(() => {
    const map: Record<string, Story[]> = {};
    (bundle?.stories ?? []).forEach(s => {
      (map[s.epic_id] ??= []).push(s);
    });
    Object.values(map).forEach(list => list.sort((a,b)=>a.priority_rank-b.priority_rank));
    return map;
  }, [bundle]);

  const productVision = bundle?.product_vision;
  const goals = productVision?.goals ?? [];
  const personas = productVision?.personas ?? [];
  const features = productVision?.features ?? [];
  const designNotes = bundle?.design_notes ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">View Plan</h1>

      <div className="flex items-center gap-3">
        <RunPicker value={runId} onChange={setRunId} />
        <button
          className="px-4 py-2 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50"
          disabled={!runId || busy}
          onClick={fetchPlan}
        >
          {busy ? "Loading…" : "Load Plan"}
        </button>
      </div>

      {err && <div className="text-rose-400 text-sm">{err}</div>}

      {bundle && (
        <div className="space-y-6">
          {/* Product Vision */}
          <Collapsible title="Product Vision" defaultOpen>
            <div className="grid md:grid-cols-3 gap-4">
              <div>
                <div className="opacity-70 text-sm mb-1">Goals</div>
                <ul className="list-disc ml-5 space-y-1">{goals.map((g,i)=><li key={i}>{g}</li>)}</ul>
              </div>
              <div>
                <div className="opacity-70 text-sm mb-1">Personas</div>
                <ul className="list-disc ml-5 space-y-1">{personas.map((p,i)=><li key={i}>{p}</li>)}</ul>
              </div>
              <div>
                <div className="opacity-70 text-sm mb-1">Features</div>
                <ul className="list-disc ml-5 space-y-1">{features.map((f,i)=><li key={i}>{f}</li>)}</ul>
              </div>
            </div>
          </Collapsible>

          {/* Technical Solution */}
          <Collapsible title="Technical Solution" defaultOpen>
            <div className="grid md:grid-cols-4 gap-4">
              <div>
                <div className="opacity-70 text-sm mb-1">Stack</div>
                <ul className="list-disc ml-5 space-y-1">{bundle.technical_solution.stack.map((s,i)=><li key={i}>{s}</li>)}</ul>
              </div>
              <div>
                <div className="opacity-70 text-sm mb-1">Modules</div>
                <ul className="list-disc ml-5 space-y-1">{bundle.technical_solution.modules.map((m,i)=><li key={i}>{m}</li>)}</ul>
              </div>
              <div className="md:col-span-2">
                <div className="opacity-70 text-sm mb-1">Interfaces</div>
                <ul className="list-disc ml-5 space-y-1">
                  {Object.entries(bundle.technical_solution.interfaces).map(([k,v])=>(
                    <li key={k}><span className="font-mono">{k}</span>: {v}</li>
                  ))}
                </ul>
                <div className="opacity-70 text-sm mt-3 mb-1">Decisions</div>
                <ul className="list-disc ml-5 space-y-1">{bundle.technical_solution.decisions.map((d,i)=><li key={i}>{d}</li>)}</ul>
              </div>
            </div>
          </Collapsible>

          {/* Epics & Stories */}
          <div className="space-y-3">
            {bundle.epics.map((e: Epic) => (
              <Collapsible key={e.id} title={`[${e.priority_rank}] ${e.title}`} defaultOpen={false}>
                <p className="opacity-80 mb-3">{e.description}</p>
                <div className="space-y-3">
                  {(storiesByEpic[e.id] ?? []).map(st => (
                    <div key={st.id} className="border border-slate-700 rounded-lg p-3">
                      <div className="flex justify-between mb-1">
                        <div className="font-semibold">[{st.priority_rank}] {st.title}</div>
                        <code className="opacity-60">{st.id}</code>
                      </div>
                      <p className="opacity-80 mb-2">{st.description}</p>

                      {!!st.tasks?.length && (
                        <>
                          <div className="opacity-70 text-sm mb-1">Tasks</div>
                          <ol className="list-decimal ml-5 space-y-1">
                            {st.tasks.map(t => <li key={t.id}>{t.title}</li>)}
                          </ol>
                        </>
                      )}

                      {!!st.acceptance?.length && (
                        <>
                          <div className="opacity-70 text-sm mt-3 mb-1">Acceptance (Gherkin)</div>
                          <div className="grid gap-2">
                            {st.acceptance.map((ac, i) => (
                              <pre key={i} className="bg-slate-950/60 border border-slate-800 rounded p-3 whitespace-pre-wrap">{ac.gherkin}</pre>
                            ))}
                          </div>
                        </>
                      )}

                      {!!st.tests?.length && (
                        <>
                          <div className="opacity-70 text-sm mt-3 mb-1">Suggested tests</div>
                          <ul className="list-disc ml-5 space-y-1">
                            {st.tests.map((t,i)=><li key={i}>{t}</li>)}
                          </ul>
                        </>
                      )}
                    </div>
                  ))}
                  {!storiesByEpic[e.id]?.length && <div className="opacity-60 text-sm">No stories for this epic yet.</div>}
                </div>
              </Collapsible>
            ))}
          </div>

          {/* Design notes */}
          {!!designNotes.length && (
            <Collapsible title="Design Notes">
              <div className="grid md:grid-cols-2 gap-3">
                {designNotes.map((dn) => (
                  <div key={dn.id} className="border border-slate-700 rounded-lg p-3">
                    <div className="flex justify-between">
                      <div className="font-semibold">{dn.title}</div>
                      <span className="text-xs opacity-70">{dn.kind}</span>
                    </div>
                    <div className="prose prose-invert mt-2" dangerouslySetInnerHTML={{__html: dn.body_md.replace(/\n/g,"<br/>")}} />
                  </div>
                ))}
              </div>
            </Collapsible>
          )}
        </div>
      )}
    </div>
  );
}
