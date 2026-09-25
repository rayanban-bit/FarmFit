"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import type { Catalog, ComparisonRow, OptimizeResult, SourceType } from "@/lib/types";
import { TECH_COLOR, n0, n1, pct, qar, signed, years } from "@/lib/format";
import { Kpi, Notice, Section, Segmented, TypeBadge } from "./ui";
import DataPanel from "./DataPanel";

interface Props {
  cat: Catalog;
  scenarioId: string;
  onScenario: (id: string) => void;
  results: Record<string, OptimizeResult>;
  loadingScenarios: boolean;
  switching: boolean;
  onEdit: () => void;
  context: Record<string, { text: string } | undefined>;
}

const TABS = [
  { id: "summary", label: "Summary" },
  { id: "compare", label: "Baseline & scenarios" },
  { id: "resources", label: "Resources & solver" },
  { id: "data", label: "Data & assumptions" },
] as const;

const YIELD_BADGE: Record<string, { t: string; c: SourceType }> = {
  aquacrop: { t: "AquaCrop", c: "scientific_model" },
  official: { t: "Official Qatar data", c: "official_qatar" },
  parameter: { t: "Unverified", c: "unverified" },
};

export default function ResultsPanel(p: Props) {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("summary");
  const [wideData, setWideData] = useState(false);
  const r = p.results[p.scenarioId];
  if (!r) return null;
  const s = r.summary;
  const base = r.baseline ?? r.baseline_free;
  const bsum = base?.summary;
  const infeasible = r.status === "INFEASIBLE" || r.portfolio.length === 0;
  const requiredExcluded = r.excluded.filter((e) => e.kind === "required_input").length;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-[var(--line-strong)] px-5 pb-3 pt-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="eyebrow">Result · {r.objective === "roi" ? "maximise 5-year ROI" : "maximise 5-year net cash flow"}</div>
            <h2 className="mt-0.5 text-[19px] font-semibold tracking-tight">Your optimized farm</h2>
          </div>
          <button className="btn" onClick={p.onEdit}>Edit inputs</button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Segmented
            value={p.scenarioId}
            disabled={p.switching}
            onChange={p.onScenario}
            options={Object.entries(p.cat.scenarios).map(([id, sc]) => ({ id, label: sc.name }))}
          />
          <span className="chip" style={{ color: r.status === "OPTIMAL" ? "var(--good)" : "var(--bad)", borderColor: "currentColor" }}>{r.status}</span>
          <span className="num text-[11px] text-[var(--muted)]">{p.switching ? "recomputing…" : `${n0(r.timing_ms)} ms · ${r.solver.n_binary} binary vars`}</span>
        </div>
        <div className="mt-1.5 text-[11.5px] text-[var(--muted)]">{r.scenario.description}</div>
      </div>

      <nav className="flex border-b border-[var(--line)] px-3">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} className="border-b-2 px-2.5 py-2 text-[12px]" style={{ borderColor: tab === t.id ? "var(--accent)" : "transparent", fontWeight: tab === t.id ? 600 : 400, color: tab === t.id ? "var(--ink)" : "var(--muted)" }}>
            {t.label}
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "summary" && (
          <>
            {(r.warnings.length > 0 || infeasible || r.accepted_planning_profile) && (
              <div className="space-y-2 px-5 pt-4">
                {infeasible && r.status === "NO_VIABLE_INVESTMENT" && (
                  <Notice tone="bad">
                    <b>No viable investment solution.</b> Every farm these limits allow has a 5-year net cash flow of zero
                    or less, so the optimizer allocated no land and a return on investment cannot be defined. Check the
                    selling prices, the CapEx and OpEx figures, and the available budget, water and energy.
                  </Notice>
                )}
                {infeasible && r.status !== "NO_VIABLE_INVESTMENT" && (
                  <Notice tone="bad">
                    No feasible portfolio was produced.{" "}
                    {requiredExcluded > 0
                      ? `${requiredExcluded} crop × technique combination${requiredExcluded === 1 ? " was" : "s were"} excluded because a required input has no value, and nothing was invented to fill the gap. Supply those inputs, or relax the budget, water or energy limits.`
                      : "The budget, water or energy limit is too small for any technique's minimum viable area. Relax a limit and re-run."}
                  </Notice>
                )}
                {r.status === "ZERO_CAPEX" && (
                  <Notice tone="warn">
                    <b>ROI is not defined for this plan.</b> Every selected system was given a capital cost of zero, so the
                    plan produces without investment and the ratio net&nbsp;gain ÷ CapEx has no finite value. The plan below
                    maximises 5-year net cash flow instead. Enter real CapEx figures to get an ROI.
                  </Notice>
                )}
                {r.accepted_planning_profile && (
                  <Notice tone="warn">
                    <b>Estimated values were used</b> for the technical assumptions you left blank — construction costs, labour,
                    maintenance, energy and water coefficients. They are order-of-magnitude figures, not sourced data, and every
                    one is marked <b>Estimate</b> in Data &amp; assumptions. Replace them with real quotations before treating
                    any number here as evidence.
                  </Notice>
                )}
                {r.warnings.map((w, i) => (<Notice key={i} tone="warn">{w}</Notice>))}
              </div>
            )}
            {!infeasible && (
              <>
                <div className="grid grid-cols-2 gap-x-5 gap-y-4 border-b border-[var(--line)] px-5 py-4">
                  <Kpi label="5-year ROI" value={pct(s.roi, 1)} tone={s.roi != null && s.roi < 0 ? "bad" : undefined} sub={bsum ? `Baseline ${pct(bsum.roi, 1)}` : undefined} />
                  <Kpi label="Payback" value={years(s.payback_years)} sub={bsum ? `Baseline ${years(bsum.payback_years)}` : undefined} />
                  <Kpi label="Annual profit" value={qar(s.profit)} sub={bsum ? `Baseline ${qar(bsum.profit)}` : `Revenue ${qar(s.revenue)}`} />
                  <Kpi label="CapEx" value={qar(s.capex)} sub={`${pct(s.capex / r.limits.budget_qar)} of budget`} />
                  <Kpi label="Annual OpEx" value={qar(s.opex)} sub={`Revenue ${qar(s.revenue)}`} />
                  <Kpi label="5-year net cash flow" value={qar(s.net_gain)} sub={bsum ? `Baseline ${qar(bsum.net_gain)}` : undefined} />
                  <Kpi label="Water" value={`${n0(s.water_m3)} m³/yr`} sub={`${pct(s.water_m3 / r.limits.water_m3_year)} of ${n0(r.limits.water_m3_year)}`} />
                  <Kpi label="Energy" value={`${n0(s.energy_kwh)} kWh/yr`} sub={`${pct(s.energy_kwh / r.limits.energy_kwh_year)} of ${n0(r.limits.energy_kwh_year)}`} />
                </div>

                {r.limiting.unallocated_share > 0.02 && (
                  <Section title="Why is land left unallocated?" aside={<span className="eyebrow">binding constraint</span>}>
                    <Notice tone={r.limiting.limiting_factor === "land" ? "info" : "warn"}>{r.limiting.headline}</Notice>
                    <table className="tbl mt-2">
                      <thead><tr><th>Limit</th><th className="r">Used</th><th className="r">Available</th><th className="r">Supports</th></tr></thead>
                      <tbody>
                        {r.limiting.limits.map((l) => (
                          <tr key={l.key} style={l.binding ? { background: "#fbf1dd" } : undefined}>
                            <td>
                              <span style={l.binding ? { fontWeight: 600, color: "var(--warn)" } : undefined}>{l.label}</span>
                              {l.binding && <span className="chip ml-1.5" style={{ borderColor: "var(--warn)", color: "var(--warn)" }}>binding</span>}
                              {l.note && <div className="mt-0.5 text-[10.5px] leading-snug text-[var(--muted)]">{l.note}</div>}
                            </td>
                            <td className="r num">{n0(l.used)}</td>
                            <td className="r num">{l.limit == null || !isFinite(l.limit) ? "—" : n0(l.limit)}</td>
                            <td className="r num">{l.land_supported_m2 == null ? "—" : `${n0(l.land_supported_m2)} m²`}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="mt-2 text-[11.5px] leading-snug text-[var(--muted)]">
                      “Supports” is how much land each limit alone would allow for the system the solver chose. The
                      smallest of them is what actually caps the farm. Unallocated land is a real result, not a gap in the
                      cadastral data — the boundary and its registered area come from the live Qatar cadastre.
                    </p>
                  </Section>
                )}

                <Section title="Portfolio" aside={<span className="eyebrow">from the solver</span>}>
                  <table className="tbl">
                    <thead><tr><th>Crop</th><th>Technique</th><th className="r">Area m²</th><th className="r">Yield t/yr</th><th className="r">Revenue QAR</th></tr></thead>
                    <tbody>
                      {r.portfolio.map((b, i) => {
                        const yb = YIELD_BADGE[b.yield_source] ?? YIELD_BADGE.parameter;
                        return (
                          <tr key={i}>
                            <td>
                              <div className="font-medium">{b.crop_name}</div>
                              <div className="text-[11px] text-[var(--muted)]">{b.plot_name} · {n0(b.share_of_plot_usable * 100)}% of plot</div>
                            </td>
                            <td>
                              <span className="mr-1.5 inline-block h-2.5 w-2.5 align-[-1px]" style={{ background: TECH_COLOR[b.technique] }} />{b.technique_name}
                              <div className="mt-0.5"><TypeBadge type={yb.c} label={`Yield: ${yb.t}`} /></div>
                            </td>
                            <td className="r num">{n0(b.area_m2)}</td>
                            <td className="r num">{n1(b.yield_kg_year / 1000)}<div className="text-[10.5px] text-[var(--muted)]">{n1(b.yield_kg_m2_year)} kg/m²</div></td>
                            <td className="r num">{n0(b.revenue)}</td>
                          </tr>
                        );
                      })}
                      <tr style={{ borderTop: "1px solid var(--line-strong)" }}>
                        <td colSpan={2} className="font-medium">Total</td>
                        <td className="r num font-medium">{n0(s.area_m2)}</td>
                        <td className="r num font-medium">{n1(s.yield_kg / 1000)}</td>
                        <td className="r num font-medium">{n0(s.revenue)}</td>
                      </tr>
                    </tbody>
                  </table>
                  <div className="mt-2 space-y-0.5 text-[11.5px] text-[var(--muted)]">
                    {r.plots.map((pl) => (
                      <div key={pl.plot_id}><span className="num">{pl.plot_id}</span>: {n0(pl.area_m2)} m² · access/infrastructure {n0(pl.access_m2)} m² · unallocated {n0(pl.unallocated_m2)} m²{p.context[pl.plot_id] ? ` · ${p.context[pl.plot_id]!.text}` : ""}</div>
                    ))}
                  </div>
                </Section>

                <Section title="Why this configuration?" aside={<span className="eyebrow">generated from model outputs only</span>}>
                  <ul className="space-y-2.5">
                    {r.explanations.map((e, i) => (
                      <li key={i} className="flex gap-2.5 text-[12.5px] leading-snug">
                        <span className="mt-[7px] inline-block h-1 w-1 shrink-0 bg-[var(--ink)]" />
                        <span>{e.text}</span>
                      </li>
                    ))}
                  </ul>
                </Section>
              </>
            )}
            {r.excluded.length > 0 && (
              <Section title="Excluded combinations" aside={<span className="eyebrow">{r.excluded.length}</span>}>
                <p className="mb-2 text-[12px] text-[var(--muted)]">
                  Every combination the optimizer refused, with its exact reason. None of these was replaced by a guessed number.
                </p>
                {(["required_input", "climate", "data", "incompatible"] as const).map((kind) => {
                  const rows = r.excluded.filter((e) => (e.kind ?? "incompatible") === kind);
                  if (!rows.length) return null;
                  const title =
                    kind === "required_input" ? "Required input unavailable — enter value"
                    : kind === "climate" ? "No thermally feasible growing window"
                    : kind === "data" ? "No usable official data"
                    : "Incompatible crop × technique";
                  return (
                    <details key={kind} className="mb-1.5 border border-[var(--line)] px-2.5 py-1.5" open={kind === "required_input"}>
                      <summary className="cursor-pointer text-[12px]">
                        <span className="font-medium" style={kind === "required_input" ? { color: "var(--warn)" } : undefined}>{title}</span>
                        <span className="num ml-2 text-[var(--muted)]">{rows.length}</span>
                      </summary>
                      <table className="tbl mt-1.5">
                        <tbody>
                          {rows.map((e, i) => (
                            <tr key={i}>
                              <td className="num whitespace-nowrap align-top">{e.plot}</td>
                              <td className="align-top">{p.cat.crops[e.crop]?.name ?? e.crop} × {p.cat.techniques[e.technique]?.name ?? e.technique}</td>
                              <td className="text-[11.5px] leading-snug text-[var(--muted)]">
                                {e.missing?.length ? e.missing.map((m) => m.label).join("; ") : e.reason}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </details>
                  );
                })}
              </Section>
            )}
          </>
        )}

        {wideData && (
          <div className="fixed inset-x-[4vw] bottom-[4vh] top-[7vh] z-50 flex flex-col border border-[var(--ink)] bg-[var(--panel)] shadow-[0_2px_0_rgba(0,0,0,0.12)]">
            <div className="flex items-center justify-between border-b border-[var(--line-strong)] px-5 py-3">
              <h3 className="h-section">Data &amp; assumptions</h3>
              <button className="btn" onClick={() => setWideData(false)}>Close</button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto px-5 py-4"><DataPanel rows={r.data_panel} wide /></div>
          </div>
        )}
        {tab === "compare" && <CompareTab r={r} p={p} />}
        {tab === "resources" && <ResourcesTab r={r} />}
        {tab === "data" && (
          <div className="px-5 py-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[12px] text-[var(--muted)]">Every input, its source, retrieval date and type. Nothing is hidden.</span>
              <button className="btn" onClick={() => setWideData(true)}>Expand table</button>
            </div>
            <DataPanel rows={r.data_panel} />
          </div>
        )}
      </div>
    </div>
  );
}

function Delta({ row }: { row: ComparisonRow }) {
  if (row.delta == null) return <span>—</span>;
  const good = row.better === "high" ? row.delta > 0 : row.delta < 0;
  const isPct = row.unit === "%";
  const txt = isPct ? signed(row.delta * 100, (x) => `${x.toFixed(1)} pp`) : row.unit === "years" ? signed(row.delta, n1) : signed(row.delta, n0);
  return <span style={{ color: Math.abs(row.delta) < 1e-9 ? "var(--muted)" : good ? "var(--good)" : "var(--bad)" }}>{txt}</span>;
}

function fmtCmp(row: ComparisonRow, v: number | null) {
  if (v == null) return row.metric === "payback_years" ? "Never" : "—";
  if (row.unit === "%") return pct(v, 1);
  if (row.unit === "years") return n1(v);
  return n0(v);
}

function CompareTab({ r, p }: { r: OptimizeResult; p: Props }) {
  const [which, setWhich] = useState<"baseline" | "baseline_free">(r.baseline ? "baseline" : "baseline_free");
  const b = r[which] ?? r.baseline ?? r.baseline_free;
  const cmp = (which === "baseline" ? r.comparison : r.comparison_free) ?? r.comparison ?? r.comparison_free;
  const cf = r.summary.cumulative_cash_flow.map((v, i) => ({ year: i, Optimized: v, Baseline: b?.summary.cumulative_cash_flow[i] ?? null }));
  const scen = Object.entries(p.cat.scenarios);
  return (
    <>
      <Section title="Optimized portfolio vs baseline" aside={r.baseline && r.baseline_free ? <Segmented value={which} onChange={setWhich} options={[{ id: "baseline", label: "Whole plot" }, { id: "baseline_free", label: "Best single option" }]} /> : undefined}>
        {b ? (
          <>
            <p className="mb-2 text-[12px] text-[var(--muted)]">
              Baseline: <b className="text-[var(--ink)]">{b.crop_name}</b> with <b className="text-[var(--ink)]">{b.technique_name.toLowerCase()}</b> only, {pct(b.scale_of_usable_area)} of the usable area. {b.definition}. It is a feasible point of the same optimization problem, so the optimum cannot be worse.
            </p>
            <table className="tbl">
              <thead><tr><th>Metric</th><th className="r">Optimized</th><th className="r">Baseline</th><th className="r">Difference</th></tr></thead>
              <tbody>
                {(cmp ?? []).map((row) => (
                  <tr key={row.metric}><td>{row.label} <span className="text-[10.5px] text-[var(--faint)]">{row.unit}</span></td><td className="r num">{fmtCmp(row, row.optimized)}</td><td className="r num">{fmtCmp(row, row.baseline)}</td><td className="r num"><Delta row={row} /></td></tr>
                ))}
              </tbody>
            </table>
            <div className="mt-4 h-[190px]">
              <div className="eyebrow mb-1">Cumulative cash flow, QAR (Year 0 = −CapEx)</div>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={cf} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#dddacf" strokeDasharray="2 3" vertical={false} />
                  <XAxis dataKey="year" tick={{ fontSize: 11 }} stroke="#8e928b" />
                  <YAxis tick={{ fontSize: 11 }} stroke="#8e928b" tickFormatter={(v) => `${Math.round(v / 1000)}k`} width={46} />
                  <Tooltip formatter={(v) => n0(Number(v))} contentStyle={{ fontSize: 12, border: "1px solid #c3bfb2", borderRadius: 2 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine y={0} stroke="#1b1e1c" />
                  <Line type="linear" dataKey="Optimized" stroke="#1f5c4d" strokeWidth={2} dot={{ r: 2 }} />
                  <Line type="linear" dataKey="Baseline" stroke="#86560f" strokeWidth={1.6} strokeDasharray="4 3" dot={{ r: 2 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </>
        ) : (
          <Notice tone="warn">No single crop × technique satisfies all constraints, so no baseline exists for this scenario.</Notice>
        )}
      </Section>

      <Section title="Scenario test" aside={p.loadingScenarios ? <span className="eyebrow">computing…</span> : undefined}>
        <p className="mb-2 text-[12px] text-[var(--muted)]">The same model and solver are re-run with a changed constraint or price. The design changes because the optimum changes, not because of a prediction.</p>
        <table className="tbl">
          <thead><tr><th>Scenario</th><th className="r">ROI</th><th className="r">Profit</th><th className="r">CapEx</th><th className="r">Water</th><th className="r">Energy</th></tr></thead>
          <tbody>
            {scen.map(([id, sc]) => {
              const x = p.results[id];
              return (
                <tr key={id} style={id === p.scenarioId ? { background: "#eef3f0" } : undefined}>
                  <td><button className="text-left font-medium underline decoration-[var(--line-strong)] underline-offset-2" onClick={() => p.onScenario(id)}>{sc.name}</button>
                    {x && <div className="text-[11px] text-[var(--muted)]">{Array.from(new Set(x.portfolio.map((b) => `${b.crop_name} (${b.technique_name.toLowerCase()})`))).join(" · ") || "no feasible plan"}</div>}
                  </td>
                  <td className="r num">{x ? pct(x.summary.roi, 0) : "…"}</td>
                  <td className="r num">{x ? n0(x.summary.profit) : "…"}</td>
                  <td className="r num">{x ? n0(x.summary.capex) : "…"}</td>
                  <td className="r num">{x ? n0(x.summary.water_m3) : "…"}</td>
                  <td className="r num">{x ? n0(x.summary.energy_kwh) : "…"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Section>
    </>
  );
}

/** y-axis max: fit the data, and include the cap only when it is on a comparable scale (otherwise it is stated in the caption). */
const yMax = (values: number[], cap: number | null) => (dataMax: number) => {
  const m = Math.max(dataMax, ...values);
  return Math.ceil((cap != null && cap <= 2.5 * m ? Math.max(m, cap) : m) * 1.1);
};

function ResourcesTab({ r }: { r: OptimizeResult }) {
  const water = r.monthly.months.map((m, i) => ({ month: m, "Water m³": r.monthly.water_m3[i] }));
  const energy = r.monthly.months.map((m, i) => ({ month: m, "Energy kWh": r.monthly.energy_kwh[i] }));
  return (
    <>
      <Section title="Monthly water" aside={<span className="eyebrow">monthly limit {r.monthly.water_cap_m3 != null ? `${n0(r.monthly.water_cap_m3)} m³` : "—"}</span>}>
        <div className="h-[170px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={water} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#dddacf" strokeDasharray="2 3" vertical={false} />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} stroke="#8e928b" />
              <YAxis tick={{ fontSize: 11 }} stroke="#8e928b" width={46} domain={[0, yMax(r.monthly.water_m3, r.monthly.water_cap_m3)]} allowDataOverflow />
              <Tooltip formatter={(v) => n0(Number(v))} contentStyle={{ fontSize: 12, border: "1px solid #c3bfb2", borderRadius: 2 }} />
              {r.monthly.water_cap_m3 != null && <ReferenceLine y={r.monthly.water_cap_m3} stroke="#9a3030" strokeDasharray="4 3" label={{ value: "monthly cap", fontSize: 10, fill: "#9a3030", position: "insideTopRight" }} />}
              <Bar dataKey="Water m³" fill="#2d6796" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Section>
      <Section title="Monthly energy" aside={<span className="eyebrow">monthly limit {r.monthly.energy_cap_kwh != null ? `${n0(r.monthly.energy_cap_kwh)} kWh` : "—"}</span>}>
        <div className="h-[170px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={energy} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#dddacf" strokeDasharray="2 3" vertical={false} />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} stroke="#8e928b" />
              <YAxis tick={{ fontSize: 11 }} stroke="#8e928b" width={46} domain={[0, yMax(r.monthly.energy_kwh, r.monthly.energy_cap_kwh)]} allowDataOverflow />
              <Tooltip formatter={(v) => n0(Number(v))} contentStyle={{ fontSize: 12, border: "1px solid #c3bfb2", borderRadius: 2 }} />
              {r.monthly.energy_cap_kwh != null && <ReferenceLine y={r.monthly.energy_cap_kwh} stroke="#9a3030" strokeDasharray="4 3" label={{ value: "monthly cap", fontSize: 10, fill: "#9a3030", position: "insideTopRight" }} />}
              <Bar dataKey="Energy kWh" fill="#a8892f" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Section>
      <Section title="Shared infrastructure">
        {r.plots.every((p) => p.infrastructure.length === 0) ? <div className="text-[12px] text-[var(--muted)]">No infrastructure built.</div> : (
          <table className="tbl">
            <thead><tr><th>Plot</th><th>Item (built once)</th><th>Serves</th><th className="r">Fixed CapEx</th><th className="r">Saved by sharing</th></tr></thead>
            <tbody>
              {r.plots.flatMap((pl) => pl.infrastructure.map((g) => (
                <tr key={pl.plot_id + g.group}><td className="num">{pl.plot_id}</td><td>{g.name}</td><td className="text-[11.5px]">{g.used_by.join(", ")}</td><td className="r num">{n0(g.fixed_capex)}</td><td className="r num">{n0(g.capex_saved_by_sharing)}</td></tr>
              )))}
            </tbody>
          </table>
        )}
      </Section>
      <Section title="Solver">
        <div className="grid grid-cols-2 gap-3 text-[12px]">
          <div><div className="eyebrow">Method</div>{r.solver.method}</div>
          <div><div className="eyebrow">Backend</div>{r.solver.backend}</div>
          <div><div className="eyebrow">Variables · binary · constraints</div><span className="num">{r.solver.n_vars} · {r.solver.n_binary} · {r.solver.n_constraints}</span></div>
          <div><div className="eyebrow">Utilisation floor</div><span className="num">{pct(r.solver.utilisation_floor_requested)} requested · {pct(r.solver.utilisation_floor_used)} used</span></div>
        </div>
        <table className="tbl mt-3">
          <thead><tr><th>k</th><th className="r">λ (ROI)</th><th className="r">Net gain</th><th className="r">CapEx</th><th className="r">F(λ)</th></tr></thead>
          <tbody>
            {r.solver.iterations.map((it) => (
              <tr key={it.k}><td className="num">{it.k}</td><td className="r num">{(it.lambda * 100).toFixed(3)}%</td><td className="r num">{n0(it.net_gain)}</td><td className="r num">{n0(it.capex)}</td><td className="r num">{it.F.toExponential(2)}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[11.5px] text-[var(--muted)]">Dinkelbach terminates when F(λ) = max N − λ·CapEx reaches 0: the incumbent then maximises N/CapEx exactly (up to solver tolerance).</p>
      </Section>
    </>
  );
}
