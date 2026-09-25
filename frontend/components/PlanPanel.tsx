"use client";

import type { Catalog, IterationRec, MissingInput, ParcelFC, SiteSummary } from "@/lib/types";
import { unresolved, type PlanState } from "@/lib/state";
import { TECH_COLOR, n0, n2 } from "@/lib/format";
import { Notice, Section } from "./ui";
import InputsStep from "./InputsStep";

interface Props {
  cat: Catalog;
  missingInputs: MissingInput[];
  site: SiteSummary | null;
  siteLoading: boolean;
  siteError: string | null;
  parcels: ParcelFC | null;
  parcelInfo: { label: string; sourceUrl: string; count: number; truncated: boolean; loading: boolean; error: string | null; zoomedOut: boolean };
  st: PlanState;
  set: (p: Partial<PlanState>) => void;
  step: number;
  setStep: (n: number) => void;
  running: boolean;
  stages: string[];
  iters: IterationRec[];
  error: string | null;
  onRun: () => void;
  onFit: () => void;
}

const STEPS = ["Land", "Crops", "Your farm", "Optimize"];

export default function PlanPanel(p: Props) {
  const { cat, parcels, st, set, step, setStep } = p;
  const chosen = (parcels?.features ?? []).filter((f) => st.selected.includes(f.properties.id));
  const area = chosen.reduce((s, f) => s + f.properties.area_m2, 0);
  const toggle = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const stillMissing = unresolved(p.missingInputs, st);

  return (
    <div className="flex h-full flex-col">
      <nav className="flex border-b border-[var(--line-strong)]">
        {STEPS.map((s, i) => (
          <button
            key={s}
            onClick={() => setStep(i + 1)}
            className="flex flex-1 items-center gap-2 border-b-2 px-3 py-2.5 text-left text-[12px]"
            style={{ borderColor: step === i + 1 ? "var(--accent)" : "transparent", color: step === i + 1 ? "var(--ink)" : "var(--muted)", fontWeight: step === i + 1 ? 600 : 400 }}
          >
            <span className="num inline-flex h-[18px] w-[18px] items-center justify-center border text-[10.5px]" style={{ borderColor: step === i + 1 ? "var(--accent)" : "var(--line-strong)" }}>{i + 1}</span>
            {s}
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {step === 1 && <LandStep {...p} chosen={chosen} area={area} />}

        {step === 2 && (
          <>
            <Section title="Crops you are willing to grow">
              <div className="space-y-1.5">
                {Object.entries(cat.crops).map(([id, c]) => (
                  <label key={id} className="flex cursor-pointer items-start gap-2.5 border border-[var(--line)] bg-white px-3 py-2">
                    <input className="mt-0.5" type="checkbox" checked={st.crops.includes(id)} onChange={() => set({ crops: toggle(st.crops, id) })} />
                    <span className="flex-1">
                      <span className="flex items-center gap-2 font-medium">
                        {c.name}
                        {c.aquacrop.supported && <span className="chip">AquaCrop (open field)</span>}
                        {c.priority === 1 && <span className="chip" style={{ borderColor: "#a8c4b9", color: "#14483b" }}>Best evidence</span>}
                      </span>
                      <span className="mt-0.5 block text-[11.5px] leading-snug text-[var(--muted)]">{c.evidence}</span>
                    </span>
                  </label>
                ))}
              </div>
            </Section>
            <Section title="Production techniques you have access to">
              <div className="space-y-1.5">
                {Object.entries(cat.techniques).map(([id, t]) => (
                  <label key={id} className="flex cursor-pointer items-start gap-2.5 border border-[var(--line)] bg-white px-3 py-2">
                    <input className="mt-1" type="checkbox" checked={st.techniques.includes(id)} onChange={() => set({ techniques: toggle(st.techniques, id) })} />
                    <span className="mt-1 inline-block h-2.5 w-2.5 shrink-0" style={{ background: TECH_COLOR[id] }} />
                    <span className="flex-1">
                      <span className="block font-medium">{t.name}</span>
                      <span className="block text-[11.5px] leading-snug text-[var(--muted)]">
                        {t.model_class === "empirical" ? "Empirical model — AquaCrop is not applied to this system." : "Qatar Open Data yield; AquaCrop where a calibrated crop file exists."}
                      </span>
                      {t.no_profile_reason && <span className="mt-0.5 block text-[11px] leading-snug" style={{ color: "var(--warn)" }}>{t.no_profile_reason}</span>}
                    </span>
                  </label>
                ))}
              </div>
              <p className="mt-2 text-[11.5px] text-[var(--muted)]">
                Combinations with no defensible number are not silently guessed: they are excluded and listed with the exact input they need.
              </p>
            </Section>
          </>
        )}

        {step === 3 && (
          <InputsStep cat={cat} missingInputs={p.missingInputs} site={p.site} siteLoading={p.siteLoading} siteError={p.siteError} st={st} set={set} />
        )}

        {step === 4 && (
          <>
            <Section title="Optimize farm">
              <div className="grid grid-cols-2 gap-3 text-[12px]">
                <Row k="Plots" v={`${chosen.length} · ${n0(area)} m²`} />
                <Row k="Crops × techniques" v={`${st.crops.length} × ${st.techniques.length}`} />
                <Row k="Objective" v={st.objective === "roi" ? "5-year ROI (Dinkelbach)" : "5-year net cash flow"} />
                <Row k="Budget" v={`QAR ${n0(st.budget)}`} />
                <Row k="Water" v={`${n0(st.water)} m³/yr`} />
                <Row k="Energy" v={`${n0(st.energy)} kWh/yr`} />
                <Row k="Soil EC" v={st.ec ? `${st.ec} dS/m` : "not provided"} />
                <Row k="Values still needed" v={stillMissing.length === 0 ? "none" : `${stillMissing.length}`} />
              </div>
              {stillMissing.length > 0 && (
                <div className="mt-3">
                  <Notice tone="warn">
                    {stillMissing.length} value{stillMissing.length === 1 ? " has" : "s have"} no figure. Any crop × technique that needs one is
                    excluded from the optimization and listed with its reason — nothing is invented. Open “Your farm” to supply them.
                  </Notice>
                </div>
              )}
              <button className="btn btn-primary mt-4 w-full" disabled={p.running || !chosen.length || !st.crops.length || !st.techniques.length} onClick={p.onRun}>
                {p.running ? "Optimizing…" : "Optimize farm"}
              </button>
              {!chosen.length && <p className="mt-2 text-[12px] text-[var(--bad)]">Select at least one cadastral plot in step 1.</p>}
              {p.error && <div className="mt-3"><Notice tone="bad">{p.error}</Notice></div>}
            </Section>
            {(p.running || p.stages.length > 0) && (
              <Section title="Solver progress" aside={<span className="eyebrow">streamed from the service</span>}>
                <ul className="space-y-1 text-[12px] text-[var(--muted)]">
                  {p.stages.map((s, i) => (<li key={i} className="flex gap-2"><span className="num text-[var(--faint)]">{String(i + 1).padStart(2, "0")}</span>{s}</li>))}
                </ul>
                {p.iters.length > 0 && (
                  <table className="tbl mt-3">
                    <thead><tr><th>Dinkelbach k</th><th className="r">λ (ROI)</th><th className="r">F(λ)</th><th className="r">MIP ms</th></tr></thead>
                    <tbody>
                      {p.iters.map((it) => (
                        <tr key={it.k}><td className="num">{it.k}</td><td className="r num">{n2(it.lambda * 100)}%</td><td className="r num">{it.F.toExponential(2)}</td><td className="r num">{n0(it.mip_ms)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Section>
            )}
          </>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-[var(--line-strong)] px-5 py-2.5">
        <button className="btn" disabled={step === 1} onClick={() => setStep(step - 1)}>Back</button>
        <span className="text-[11.5px] text-[var(--muted)]">Step {step} of 4</span>
        {step < 4 ? <button className="btn btn-primary" onClick={() => setStep(step + 1)}>Next</button> : <span className="w-[60px]" />}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (<div><div className="eyebrow">{k}</div><div className="num">{v}</div></div>);
}

function LandStep({ parcels, parcelInfo, st, set, chosen, area, onFit }: Props & { chosen: ParcelFC["features"]; area: number }) {
  return (
    <>
      <Section title="Select cadastral plots" aside={<span className="eyebrow">live service</span>}>
        <Notice>
          {parcelInfo.label}. Plots, boundaries and registered areas come from the State of Qatar cadastral FeatureServer —
          nothing here is demo geometry.{" "}
          <a className="underline underline-offset-2" href={parcelInfo.sourceUrl} target="_blank" rel="noreferrer">service</a>
        </Notice>
        <p className="mt-2 text-[12px] text-[var(--muted)]">Pan or zoom the map, then click plots to select them. The optimizer shares one budget, water and energy pool across everything you select.</p>
        <div className="mt-2 grid grid-cols-[1fr_auto] items-end gap-2">
          <label className="block text-[11px] text-[var(--muted)]">
            Hide plots smaller than (m²)
            <input className="field mt-0.5" type="number" min={0} step={500} value={st.minPlotArea} onChange={(e) => set({ minPlotArea: Number(e.target.value) })} />
          </label>
          <button className="btn" disabled={!chosen.length} onClick={onFit}>Zoom to selection</button>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <button className="btn" disabled={!chosen.length} onClick={() => set({ selected: [] })}>Clear selection</button>
          <span className="text-[11.5px] text-[var(--muted)]">
            {parcelInfo.loading ? "loading plots…" : parcelInfo.zoomedOut ? "zoom in to load plots" : `${parcelInfo.count} plots in view`}
            {parcelInfo.truncated && " (truncated — zoom in for the rest)"}
          </span>
        </div>
        {parcelInfo.error && <div className="mt-2"><Notice tone="bad">{parcelInfo.error}</Notice></div>}
      </Section>

      <div className="px-5 py-2">
        {chosen.length === 0 ? (
          <p className="text-[12px] text-[var(--muted)]">No plots selected yet. Click a plot on the map.</p>
        ) : (
          <table className="tbl">
            <thead><tr><th>Plot (PIN)</th><th>Planning decision</th><th className="r">Registered m²</th></tr></thead>
            <tbody>
              {chosen.map((f) => {
                const q = f.properties;
                return (
                  <tr key={q.id} className="cursor-pointer hover:bg-[#f0eee6]" onClick={() => set({ selected: st.selected.filter((x) => x !== q.id) })}>
                    <td className="num">{q.id}</td>
                    <td className="text-[11.5px] text-[var(--muted)]">{(q.PD_NO as string) || "—"}</td>
                    <td className="r num">{n0(q.registered_area_m2 ?? q.area_m2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="mx-5 my-3 border-t border-[var(--line-strong)] pt-3">
        <div className="grid grid-cols-3 gap-3">
          <div><div className="eyebrow">Selected area</div><div className="num text-[18px]">{n0(area)} m²</div></div>
          <div><div className="eyebrow">Plots</div><div className="num text-[18px]">{chosen.length}</div></div>
          <div><div className="eyebrow">Plot IDs (PIN)</div><div className="num text-[11.5px] leading-snug">{chosen.map((c) => c.properties.id).join(", ") || "—"}</div></div>
        </div>
        {parcels && chosen.length > 0 && (
          <p className="mt-2 text-[11px] text-[var(--muted)]">
            Area shown is the officially registered PDAREA. The geodesic area recomputed from the returned boundary differs by about 0.2%, which the data panel reports per plot.
          </p>
        )}
      </div>
    </>
  );
}

