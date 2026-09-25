"use client";

import { useMemo, useState } from "react";
import type { Catalog, FactState, MissingInput, SiteSummary } from "@/lib/types";
import { inputKey, unresolved, type PlanState } from "@/lib/state";
import { TECH_COLOR, n0, n1 } from "@/lib/format";
import { Notice, Section } from "./ui";

interface Props {
  cat: Catalog;
  missingInputs: MissingInput[];
  site: SiteSummary | null;
  siteLoading: boolean;
  siteError: string | null;
  st: PlanState;
  set: (p: Partial<PlanState>) => void;
}

const STATE_STYLE: Record<FactState, { bg: string; fg: string; bd: string; label: string }> = {
  verified: { bg: "#dce9e3", fg: "#14483b", bd: "#a8c4b9", label: "Verified" },
  estimate: { bg: "#f4ecd9", fg: "#86560f", bd: "#dcc79b", label: "Estimate" },
  unavailable: { bg: "#f6e4e4", fg: "#6d2020", bd: "#dfb2b2", label: "Unavailable" },
};

export function StateBadge({ state, label }: { state: FactState; label?: string }) {
  const s = STATE_STYLE[state];
  return <span className="chip" style={{ background: s.bg, color: s.fg, borderColor: s.bd }}>{label ?? s.label}</span>;
}

const GROUP_TITLE: Record<string, string> = {
  crops: "Crop costs per cycle",
  yields: "Yields with no official Qatar figure",
  techniques: "System capital, running and resource costs",
  infrastructure: "Shared infrastructure",
  defaults: "Utility tariffs",
};

export default function InputsStep({ cat, missingInputs, site, siteLoading, siteError, st, set }: Props) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const setInput = (k: string, v: string) => set({ inputs: { ...st.inputs, [k]: v } });

  const essentials = missingInputs.filter((m) => m.tier === "essential" && (m.kind !== "crops" || st.crops.includes(m.owner)));
  const advanced = missingInputs.filter((m) => m.tier === "advanced");
  const stillMissing = unresolved(missingInputs, st);
  const blocking = stillMissing.filter((m) => !m.has_profile_value);

  const advGroups = useMemo(() => {
    const g: Record<string, MissingInput[]> = {};
    for (const m of advanced) (g[m.kind] ??= []).push(m);
    return g;
  }, [advanced]);

  return (
    <>
      {/* ------------------------------------------------ what we already know */}
      <Section
        title="Determined from your plots"
        aside={<span className="eyebrow">{siteLoading ? "reading sources…" : "you don't enter these"}</span>}
      >
        {siteError ? (
          <Notice tone="warn">Could not read the site data: {siteError}. You can still continue; anything unavailable is marked.</Notice>
        ) : !site ? (
          <p className="text-[12px] text-[var(--muted)]">{siteLoading ? "Reading the cadastre, weather and soil for your plots…" : "Select plots in step 1."}</p>
        ) : (
          <>
            <div className="mb-2 flex items-baseline gap-3">
              <span className="num text-[18px]">{n0(site.total_area_m2)} m²</span>
              <span className="text-[12px] text-[var(--muted)]">across {site.plots.length} plot{site.plots.length === 1 ? "" : "s"}, from the cadastre</span>
            </div>
            {site.plots.map((p) => (
              <details key={p.plot_id} className="mb-1.5 border border-[var(--line)] px-2.5 py-1.5" open={site.plots.length === 1}>
                <summary className="cursor-pointer text-[12px]">
                  <span className="num font-medium">{p.plot_id}</span>
                  <span className="ml-2 text-[var(--muted)]">{n0(p.area_m2)} m²</span>
                  <span className="ml-2 text-[11px] text-[var(--faint)]">
                    {p.facts.filter((f) => f.state === "verified").length} verified ·{" "}
                    {p.facts.filter((f) => f.state === "unavailable").length} unavailable
                  </span>
                </summary>
                <table className="tbl mt-1.5">
                  <tbody>
                    {p.facts.map((f) => (
                      <tr key={f.key}>
                        <td className="align-top">
                          <div>{f.label}</div>
                          <div className="mt-0.5 text-[10.5px] leading-snug text-[var(--muted)]">{f.note}</div>
                        </td>
                        <td className="r num whitespace-nowrap align-top">
                          {f.value == null ? <span style={{ color: "var(--warn)" }}>—</span> : <>{f.value} <span className="text-[10.5px] text-[var(--muted)]">{f.unit}</span></>}
                        </td>
                        <td className="align-top"><StateBadge state={f.state} /></td>
                        <td className="max-w-[150px] align-top text-[10.5px] leading-snug text-[var(--muted)]">
                          {f.url ? <a className="underline underline-offset-2" href={f.url} target="_blank" rel="noreferrer">{f.source}</a> : f.source}
                          {f.date && <div className="text-[var(--faint)]">{f.date}</div>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            ))}
            {site.yields.length > 0 && (
              <details className="mt-2 border border-[var(--line)] px-2.5 py-1.5">
                <summary className="cursor-pointer text-[12px]">
                  Crop yields
                  <span className="ml-2 text-[11px] text-[var(--faint)]">
                    {site.yields.filter((y) => y.state === "verified").length} from official Qatar data ·{" "}
                    {site.yields.filter((y) => y.state !== "verified").length} estimated or unavailable
                  </span>
                </summary>
                <table className="tbl mt-1.5">
                  <tbody>
                    {site.yields.map((y) => (
                      <tr key={`${y.crop}-${y.technique}`}>
                        <td>
                          <span className="mr-1.5 inline-block h-2.5 w-2.5 align-[-1px]" style={{ background: TECH_COLOR[y.technique] }} />
                          {y.crop_name} · {y.technique_name}
                        </td>
                        <td className="r num whitespace-nowrap">{y.value == null ? "—" : `${n1(y.value)} kg/m²`}</td>
                        <td><StateBadge state={y.state} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
          </>
        )}
      </Section>

      {/* ------------------------------------------------ the short form */}
      <Section title="Your farm" aside={<span className="eyebrow">what only you can tell us</span>}>
        <div className="space-y-3">
          <Field label="Budget for the investment" hint="QAR available up front, at Year 0">
            <input className="field" type="number" min={0} value={st.budget} onChange={(e) => set({ budget: Number(e.target.value) })} />
          </Field>
          <Field label="Water you can use in a year" hint="m³/year — your total annual allowance.">
            <input className="field" type="number" min={0} value={st.water} onChange={(e) => set({ water: Number(e.target.value) })} />
          </Field>
          <Field label="Electricity you can use in a year" hint="kWh/year">
            <input className="field" type="number" min={0} value={st.energy} onChange={(e) => set({ energy: Number(e.target.value) })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Most water in one month" hint="m³/month. Optional.">
              <input className="field" type="number" min={0} placeholder="no limit" value={st.waterPeak} onChange={(e) => set({ waterPeak: e.target.value })} />
            </Field>
            <Field label="Most electricity in one month" hint="kWh/month. Optional.">
              <input className="field" type="number" min={0} placeholder="no limit" value={st.energyPeak} onChange={(e) => set({ energyPeak: e.target.value })} />
            </Field>
          </div>
          <p className="-mt-1 text-[11px] leading-snug text-[var(--muted)]">
            Fill the two monthly boxes only if a pump, well or contract physically caps a single month. Left blank, the
            annual allowance can be drawn whenever the crops need it — which is what an annual quota means.
          </p>
        </div>

        <div className="mt-4">
          <div className="mb-1 flex items-baseline justify-between">
            <span className="text-[12px] font-medium">Price you expect to sell at</span>
            <span className="eyebrow">QAR / kg</span>
          </div>
          <p className="mb-2 text-[11px] leading-snug text-[var(--muted)]">
            Qatar publishes no machine-readable farm-gate price series, so this is yours to set. The figures shown are
            rough estimates — replace them with your own.
          </p>
          <div className="space-y-1.5">
            {essentials.map((m) => {
              const k = inputKey(m);
              const typed = (st.inputs[k] ?? "") !== "";
              return (
                <div key={k} className="grid grid-cols-[1fr_96px_92px] items-center gap-2">
                  <span className="text-[12px]">{cat.crops[m.owner]?.name ?? m.owner}</span>
                  <input
                    className="field"
                    type="number"
                    min={0}
                    step="0.25"
                    placeholder={m.profile_value != null ? String(m.profile_value) : "enter"}
                    value={st.inputs[k] ?? ""}
                    onChange={(e) => setInput(k, e.target.value)}
                  />
                  <StateBadge state={typed ? "verified" : m.has_profile_value ? "estimate" : "unavailable"} label={typed ? "Yours" : m.has_profile_value ? "Estimate" : "Needed"} />
                </div>
              );
            })}
          </div>
        </div>

        <div className="mt-4">
          <Field label="Measured soil salinity (ECe)" hint="dS/m, from a laboratory test. No parcel-level salinity data exists for Qatar, so leaving this blank simply means no salinity penalty is applied — the result says so.">
            <input className="field" type="number" min={0} step="0.1" placeholder="not measured" value={st.ec} onChange={(e) => set({ ec: e.target.value })} />
          </Field>
        </div>
      </Section>

      {/* ------------------------------------------------ everything technical */}
      <Section
        title="Advanced assumptions"
        aside={<button className="btn" onClick={() => setShowAdvanced(!showAdvanced)}>{showAdvanced ? "Hide" : `Edit ${advanced.length}`}</button>}
      >
        <label className="flex cursor-pointer items-start gap-2.5 border border-[var(--line-strong)] bg-white px-3 py-2">
          <input className="mt-0.5" type="checkbox" checked={st.acceptProfile} onChange={(e) => set({ acceptProfile: e.target.checked })} />
          <span className="flex-1">
            <span className="block font-medium">Use estimated values for the technical assumptions</span>
            <span className="mt-0.5 block text-[11.5px] leading-snug text-[var(--muted)]">
              Construction costs, labour, maintenance, energy and water coefficients. These are order-of-magnitude
              estimates, <b>not</b> sourced figures — they are labelled “Estimate” everywhere they appear. Turn this off
              to enter every figure yourself.
            </span>
          </span>
        </label>

        {blocking.length > 0 && (
          <div className="mt-2">
            <Notice tone="warn">
              {blocking.length} value{blocking.length === 1 ? " has" : "s have"} no estimate at all and need a real quotation —
              vertical farming is the main one. Anything depending on them stays excluded from the optimization rather than
              being guessed.
            </Notice>
          </div>
        )}

        {!showAdvanced ? (
          <p className="mt-2 text-[12px] text-[var(--muted)]">
            {st.acceptProfile
              ? `${advanced.length - blocking.length} technical assumptions are filled with estimates. Open them to review or replace any of them.`
              : `${advanced.length} technical assumptions need values before the optimizer will use the affected systems.`}
          </p>
        ) : (
          <div className="mt-2">
            {Object.entries(advGroups).map(([kind, list]) => (
              <div key={kind} className="mt-3">
                <div className="eyebrow mb-1">{GROUP_TITLE[kind] ?? kind}</div>
                <div className="space-y-1.5">
                  {list.map((m) => {
                    const k = inputKey(m);
                    const typed = (st.inputs[k] ?? "") !== "";
                    const byEstimate = !typed && st.acceptProfile && m.has_profile_value;
                    const unavailable = !typed && !byEstimate;
                    return (
                      <div key={k} className="grid grid-cols-[1fr_104px] items-center gap-2 border-b border-[var(--line)] pb-1.5">
                        <div>
                          <div className="text-[12px] leading-snug">{m.label}</div>
                          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                            <StateBadge
                              state={typed ? "verified" : byEstimate ? "estimate" : "unavailable"}
                              label={typed ? "Yours" : byEstimate ? "Estimate" : m.has_profile_value ? "Enter value" : "Quotation needed"}
                            />
                            <span className="text-[10.5px] text-[var(--faint)]">{m.unit}</span>
                          </div>
                          {m.note && <div className="mt-0.5 text-[10.5px] leading-snug text-[var(--muted)]">{m.note}</div>}
                        </div>
                        <input
                          className="field"
                          type="number"
                          min={0}
                          step="any"
                          placeholder={m.profile_value != null ? String(m.profile_value) : "enter"}
                          value={st.inputs[k] ?? ""}
                          onChange={(e) => setInput(k, e.target.value)}
                          style={unavailable ? { borderColor: "var(--warn)", background: "#fbf1dd" } : undefined}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Planning rules" aside={<span className="eyebrow">modelling choices</span>}>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Objective">
            <select className="field" value={st.objective} onChange={(e) => set({ objective: e.target.value as "roi" | "net_profit" })}>
              <option value="roi">5-year ROI (ratio)</option>
              <option value="net_profit">5-year net cash flow</option>
            </select>
          </Field>
          <Field label="Min. land utilisation">
            <input className="field" type="number" min={0} max={1} step="0.05" value={st.floor} onChange={(e) => set({ floor: Number(e.target.value) })} />
          </Field>
          <Field label="Access / infrastructure share">
            <input className="field" type="number" min={0} max={0.4} step="0.01" value={st.access} onChange={(e) => set({ access: Number(e.target.value) })} />
          </Field>

        </div>
        <p className="mt-2 text-[11.5px] leading-snug text-[var(--muted)]">
          ROI is a ratio, so maximising it can favour a small cheap farm on a large plot; the utilisation floor says how
          much land you intend to use, and the net-cash-flow objective maximises absolute return instead.
        </p>
      </Section>
    </>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="mb-1 text-[12px] font-medium">{label}</div>
      {children}
      {hint && <div className="mt-0.5 text-[11px] leading-snug text-[var(--muted)]">{hint}</div>}
    </label>
  );
}
