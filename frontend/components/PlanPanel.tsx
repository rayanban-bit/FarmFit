"use client";

import { useState } from "react";
import type { Catalog, IterationRec, ParcelFC } from "@/lib/types";
import type { PlanState } from "@/lib/state";
import { selectedAreaM2 } from "@/lib/layout";
import { TECH_COLOR, n0, n2 } from "@/lib/format";
import { Notice, Section, TypeBadge } from "./ui";

interface Props {
  cat: Catalog;
  parcels: ParcelFC;
  parcelLabel: string;
  parcelMode: "demo" | "live";
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

const STEPS = ["Land", "Options", "Constraints", "Optimize"];

export default function PlanPanel(p: Props) {
  const { cat, parcels, st, set, step, setStep } = p;
  const chosen = parcels.features.filter((f) => st.selected.includes(f.properties.id));
  const area = selectedAreaM2(chosen);
  const toggle = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

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
        {step === 1 && (
          <>
            <Section title="Select land" aside={<span className="eyebrow">{p.parcelMode === "demo" ? "Demo geometry" : "Live cadastre"}</span>}>
              <Notice tone={p.parcelMode === "demo" ? "warn" : "info"}>
                {p.parcelLabel}. {p.parcelMode === "demo" && "The public Qatar GIS server exposes no parcel layer; these polygons are illustrative shapes in farming districts. See README for connecting a real service."}
              </Notice>
              <p className="mt-2 text-[12px] text-[var(--muted)]">Click plots on the map or tick them below. The optimizer allocates one shared budget, water and energy across all selected plots.</p>
              <div className="mt-2 flex gap-2">
                <button className="btn" onClick={() => set({ selected: parcels.features.map((f) => f.properties.id) })}>Select all</button>
                <button className="btn" onClick={() => set({ selected: [] })}>Clear</button>
                <button className="btn" disabled={!chosen.length} onClick={p.onFit}>Zoom to selection</button>
              </div>
            </Section>
            <div className="px-5 py-2">
              <table className="tbl">
                <thead><tr><th></th><th>Plot</th><th>District</th><th className="r">Area m²</th></tr></thead>
                <tbody>
                  {parcels.features.map((f) => {
                    const on = st.selected.includes(f.properties.id);
                    return (
                      <tr key={f.properties.id} className="cursor-pointer hover:bg-[#f0eee6]" onClick={() => set({ selected: toggle(st.selected, f.properties.id) })}>
                        <td className="w-6"><input type="checkbox" checked={on} readOnly /></td>
                        <td><div className="font-medium">{f.properties.name}</div><div className="num text-[11px] text-[var(--muted)]">{f.properties.id}</div></td>
                        <td className="text-[var(--muted)]">{f.properties.district}</td>
                        <td className="r num">{n0(selectedAreaM2([f]))}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mx-5 my-3 border-t border-[var(--line-strong)] pt-3">
              <div className="grid grid-cols-3 gap-3">
                <div><div className="eyebrow">Selected area</div><div className="num text-[18px]">{n0(area)} m²</div></div>
                <div><div className="eyebrow">Plots</div><div className="num text-[18px]">{chosen.length}</div></div>
                <div><div className="eyebrow">Plot IDs</div><div className="num text-[12px] leading-snug">{chosen.map((c) => c.properties.id).join(", ") || "—"}</div></div>
              </div>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <Section title="Crops you are willing to grow">
              <div className="space-y-1.5">
                {Object.entries(cat.crops).map(([id, c]) => (
                  <label key={id} className="flex cursor-pointer items-center gap-2.5 border border-[var(--line)] bg-white px-3 py-2">
                    <input type="checkbox" checked={st.crops.includes(id)} onChange={() => set({ crops: toggle(st.crops, id) })} />
                    <span className="flex-1 font-medium">{c.name}</span>
                    {c.aquacrop.supported ? <span className="chip" title="Open-field simulation with FAO AquaCrop">AquaCrop (open field)</span> : <span className="chip">No AquaCrop crop file</span>}
                  </label>
                ))}
              </div>
            </Section>
            <Section title="Production techniques you have access to">
              <div className="space-y-1.5">
                {Object.entries(cat.techniques).map(([id, t]) => (
                  <label key={id} className="flex cursor-pointer items-start gap-2.5 border border-[var(--line)] bg-white px-3 py-2">
                    <input className="mt-1" type="checkbox" checked={st.techniques.includes(id)} onChange={() => set({ techniques: toggle(st.techniques, id) })} />
                    <span className="mt-1 inline-block h-2.5 w-2.5" style={{ background: TECH_COLOR[id] }} />
                    <span className="flex-1">
                      <span className="block font-medium">{t.name}</span>
                      <span className="block text-[11.5px] text-[var(--muted)]">
                        {t.model_class === "empirical" ? "Empirical model (sourced or user-supplied parameters). AquaCrop is not applied." : "Qatar Open Data yield; AquaCrop where a crop file exists."}
                      </span>
                      <span className="block text-[11.5px] text-[var(--muted)]">Compatible: {t.compatible_crops.map((c) => cat.crops[c].name).join(", ")}</span>
                    </span>
                  </label>
                ))}
              </div>
              <p className="mt-2 text-[11.5px] text-[var(--muted)]">Incompatible crop × technique pairs are removed before optimization. Options with no thermally feasible growing window or no usable data are excluded with the reason shown in the results.</p>
            </Section>
          </>
        )}

        {step === 3 && <ConstraintsStep {...p} />}

        {step === 4 && (
          <>
            <Section title="Optimize farm">
              <div className="grid grid-cols-2 gap-3 text-[12px]">
                <Row k="Plots" v={`${chosen.length} · ${n0(area)} m²`} />
                <Row k="Crops" v={st.crops.length} />
                <Row k="Techniques" v={st.techniques.length} />
                <Row k="Objective" v={st.objective === "roi" ? "5-year ROI (Dinkelbach)" : "5-year net cash flow"} />
                <Row k="Budget" v={`QAR ${n0(st.budget)}`} />
                <Row k="Water" v={`${n0(st.water)} m³/yr`} />
                <Row k="Energy" v={`${n0(st.energy)} kWh/yr`} />
                <Row k="Soil EC" v={st.ec ? `${st.ec} dS/m` : "not provided"} />
              </div>
              <button className="btn btn-primary mt-4 w-full" disabled={p.running || !chosen.length || !st.crops.length || !st.techniques.length} onClick={p.onRun}>
                {p.running ? "Optimizing…" : "Optimize farm"}
              </button>
              {!chosen.length && <p className="mt-2 text-[12px] text-[var(--bad)]">Select at least one plot in step 1.</p>}
              {p.error && <div className="mt-3"><Notice tone="bad">{p.error}</Notice></div>}
            </Section>
            {(p.running || p.stages.length > 0) && (
              <Section title="Solver progress" aside={<span className="eyebrow">live from the service</span>}>
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

function Labeled({ label, badge, hint, children }: { label: string; badge: React.ReactNode; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-[12px] font-medium">{label}</span>
        {badge}
      </div>
      {children}
      {hint && <div className="mt-0.5 text-[11px] text-[var(--muted)]">{hint}</div>}
    </label>
  );
}

function ConstraintsStep({ cat, st, set }: Props) {
  const [adv, setAdv] = useState(false);
  const setOv = (group: string, id: string, field: string, v: string) => {
    const cur = { ...(st.overrides[group] ?? {}) };
    const f = { ...(cur[id] ?? {}) };
    if (v === "" || !Number.isFinite(Number(v))) delete f[field];
    else f[field] = Number(v);
    cur[id] = f;
    set({ overrides: { ...st.overrides, [group]: cur } });
  };
  const ovVal = (group: string, id: string, field: string) => st.overrides[group]?.[id]?.[field];

  return (
    <>
      <Section title="Resources and budget">
        <div className="space-y-3">
          <Labeled label="Budget (maximum CapEx)" badge={<TypeBadge type="user_supplied" />} hint="QAR, one-off investment at Year 0">
            <input className="field" type="number" min={0} value={st.budget} onChange={(e) => set({ budget: Number(e.target.value) })} />
          </Labeled>
          <Labeled label="Available water" badge={<TypeBadge type="user_supplied" />} hint="m³ per year. Each month is limited to (annual ÷ 12) × peak factor.">
            <input className="field" type="number" min={0} value={st.water} onChange={(e) => set({ water: Number(e.target.value) })} />
          </Labeled>
          <Labeled label="Available energy" badge={<TypeBadge type="user_supplied" />} hint="kWh per year, same monthly rule">
            <input className="field" type="number" min={0} value={st.energy} onChange={(e) => set({ energy: Number(e.target.value) })} />
          </Labeled>
          <Labeled label="Measured soil salinity / EC (ECe)" badge={<TypeBadge type="user_supplied" label={st.ec ? "User supplied" : "Missing — optional"} />} hint="dS/m. SoilGrids has no salinity layer. If blank, no salinity yield penalty is applied and the result says so.">
            <input className="field" type="number" min={0} step="0.1" placeholder="not provided" value={st.ec} onChange={(e) => set({ ec: e.target.value })} />
          </Labeled>
        </div>
      </Section>

      <Section title="Selling prices" aside={<span className="eyebrow">QAR / kg</span>}>
        <div className="space-y-2">
          {st.crops.map((id) => {
            const c = cat.crops[id];
            const edited = (st.prices[id] ?? "") !== "";
            return (
              <div key={id} className="grid grid-cols-[1fr_92px_128px] items-center gap-2">
                <span>{c.name}</span>
                <input className="field" type="number" min={0} step="0.1" placeholder={String(c.price_qar_kg.value)} value={st.prices[id] ?? ""} onChange={(e) => set({ prices: { ...st.prices, [id]: e.target.value } })} />
                <TypeBadge type={edited ? "user_supplied" : "prototype_assumption"} />
              </div>
            );
          })}
        </div>
        <p className="mt-2 text-[11.5px] text-[var(--muted)]">No Qatar price dataset is integrated; the placeholders are developer estimates. Overwrite them with your own prices.</p>
      </Section>

      <Section title="Planning rules" aside={<TypeBadge type="prototype_assumption" label="Editable defaults" />}>
        <div className="grid grid-cols-2 gap-3">
          <Labeled label="Objective" badge={null}>
            <select className="field" value={st.objective} onChange={(e) => set({ objective: e.target.value as "roi" | "net_profit" })}>
              <option value="roi">5-year ROI (ratio)</option>
              <option value="net_profit">5-year net cash flow</option>
            </select>
          </Labeled>
          <Labeled label="Min. land utilisation" badge={null}>
            <input className="field" type="number" min={0} max={1} step="0.05" value={st.floor} onChange={(e) => set({ floor: Number(e.target.value) })} />
          </Labeled>
          <Labeled label="Access / infrastructure share" badge={null}>
            <input className="field" type="number" min={0} max={0.4} step="0.01" value={st.access} onChange={(e) => set({ access: Number(e.target.value) })} />
          </Labeled>
          <Labeled label="Monthly peak factor" badge={null}>
            <input className="field" type="number" min={1} max={6} step="0.1" value={st.peak} onChange={(e) => set({ peak: Number(e.target.value) })} />
          </Labeled>
        </div>
        <p className="mt-2 text-[11.5px] text-[var(--muted)]">ROI is a ratio and can be maximised by a small, cheap farm; the utilisation floor states how much of the land you intend to use. If it cannot be met within your limits it is relaxed and the result says so.</p>
      </Section>

      <Section title="Unit prices" aside={<span className="eyebrow">optional</span>}>
        <div className="grid grid-cols-2 gap-3">
          <Labeled label="Electricity (QAR/kWh)" badge={<TypeBadge type={st.electricity ? "user_supplied" : "prototype_assumption"} />}>
            <input className="field" type="number" min={0} step="0.01" placeholder={String(cat.defaults.electricity_qar_kwh.value)} value={st.electricity} onChange={(e) => set({ electricity: e.target.value })} />
          </Labeled>
          <Labeled label="Water (QAR/m³)" badge={<TypeBadge type={st.waterPrice ? "user_supplied" : "prototype_assumption"} />}>
            <input className="field" type="number" min={0} step="0.05" placeholder={String(cat.defaults.water_qar_m3.value)} value={st.waterPrice} onChange={(e) => set({ waterPrice: e.target.value })} />
          </Labeled>
        </div>
      </Section>

      <Section title="Editable cost and resource assumptions" aside={<button className="btn" onClick={() => setAdv(!adv)}>{adv ? "Hide" : "Show"}</button>}>
        {!adv ? (
          <p className="text-[12px] text-[var(--muted)]">CapEx, OpEx, energy, water coefficients and infrastructure costs are prototype assumptions until you replace them. Edited values are relabelled “User supplied”.</p>
        ) : (
          <div className="space-y-4">
            {st.techniques.map((tid) => {
              const t = cat.techniques[tid];
              const fields: [string, string, number | null][] = [
                ["capex_qar_m2", "CapEx QAR/m²", t.capex_qar_m2.value],
                ["opex_qar_m2_year", "OpEx QAR/m²/yr", t.opex_qar_m2_year.value],
                ["energy_kwh_m2_year", "Energy kWh/m²/yr", t.energy_kwh_m2_year.value],
                ["water_coefficient", "Water coefficient", t.water_coefficient.value],
                ["fixed_capex_qar", "Fixed CapEx QAR/plot", t.fixed_capex_qar.value],
                ["min_area_m2", "Min. area m²", t.min_area_m2.value],
              ];
              return (
                <div key={tid}>
                  <div className="mb-1 flex items-center gap-2 font-medium"><span className="inline-block h-2.5 w-2.5" style={{ background: TECH_COLOR[tid] }} />{t.name}</div>
                  <div className="grid grid-cols-3 gap-2">
                    {fields.map(([f, label, def]) => (
                      <label key={f} className="block text-[11px] text-[var(--muted)]">
                        {label}
                        <input className="field mt-0.5" type="number" min={0} placeholder={String(def)} value={ovVal("techniques", tid, f) ?? ""} onChange={(e) => setOv("techniques", tid, f, e.target.value)} />
                      </label>
                    ))}
                  </div>
                </div>
              );
            })}
            <div>
              <div className="mb-1 font-medium">Shared infrastructure (paid once per plot)</div>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(cat.groups).map(([gid, g]) => (
                  <label key={gid} className="block text-[11px] text-[var(--muted)]">
                    {g.name.split(" (")[0]} QAR
                    <input className="field mt-0.5" type="number" min={0} placeholder={String(g.fixed_capex_qar.value)} value={ovVal("infrastructure", gid, "fixed_capex_qar") ?? ""} onChange={(e) => setOv("infrastructure", gid, "fixed_capex_qar", e.target.value)} />
                  </label>
                ))}
              </div>
            </div>
          </div>
        )}
      </Section>
    </>
  );
}
