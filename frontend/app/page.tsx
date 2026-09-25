"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Catalog, ExplorationArea, IterationRec, MissingInput, OptimizeResult, ParcelFC, SiteSummary } from "@/lib/types";
import { API, compareScenarios, getCatalog, getContext, getExplorationArea, getParcels, getSiteSummary, optimizeStream } from "@/lib/api";
import { buildRequest, initialState, unresolved, type PlanState } from "@/lib/state";
import { layoutPlot } from "@/lib/layout";
import { n0 } from "@/lib/format";
import PlanPanel from "@/components/PlanPanel";
import ResultsPanel from "@/components/ResultsPanel";
import { Legend, MIN_PARCEL_ZOOM, type MapPiece } from "@/components/MapView";
import { Notice } from "@/components/ui";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false, loading: () => <div className="h-full w-full bg-[var(--bg)]" /> });

export default function Page() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [missingInputs, setMissingInputs] = useState<MissingInput[]>([]);
  const [parcels, setParcels] = useState<ParcelFC | null>(null);
  const [parcelInfo, setParcelInfo] = useState({
    label: "State of Qatar — approved cadastral plot boundaries",
    sourceUrl: "https://services.gisqatar.org.qa/server/rest/services/Vector/CadastrePlots/FeatureServer/0",
    count: 0, truncated: false, loading: false, error: null as string | null, zoomedOut: false,
  });
  const [st, setSt] = useState<PlanState | null>(null);
  const [step, setStep] = useState(1);
  const [mode, setMode] = useState<"plan" | "results">("plan");
  const [running, setRunning] = useState(false);
  const [stages, setStages] = useState<string[]>([]);
  const [iters, setIters] = useState<IterationRec[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, OptimizeResult>>({});
  const [scenarioId, setScenarioId] = useState("normal");
  const [loadingScen, setLoadingScen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [fitToken, setFitToken] = useState(0);
  const [focus, setFocus] = useState<string[] | null>(null);
  const [context, setContext] = useState<Record<string, { text: string } | undefined>>({});
  const [explore, setExplore] = useState<ExplorationArea | null>(null);
  const [exploreReady, setExploreReady] = useState(false);
  const [showExplore, setShowExplore] = useState(false);
  const [site, setSite] = useState<SiteSummary | null>(null);
  const [siteLoading, setSiteLoading] = useState(false);
  const [siteError, setSiteError] = useState<string | null>(null);
  const siteReq = useRef(0);
  const runRef = useRef(0);
  const parcelReq = useRef(0);
  /** every plot loaded so far, so a selection survives panning away from it */
  const [known, setKnown] = useState<Record<string, ParcelFC["features"][number]>>({});

  useEffect(() => {
    getCatalog()
      .then((c) => {
        setCat(c);
        setMissingInputs(c.missing_inputs ?? []);
        setSt(initialState(c));
      })
      .catch((e) => setLoadError(String(e.message ?? e)));
    // The opening viewport is chosen from live cadastral data, not hardcoded. If it cannot be determined
    // the map still opens, on a documented fallback extent.
    getExplorationArea()
      .then((a) => setExplore(a))
      .catch(() => setExplore(null))
      .finally(() => setExploreReady(true));
  }, []);

  const set = useCallback((p: Partial<PlanState>) => setSt((s) => (s ? { ...s, ...p } : s)), []);

  // ---- live cadastral plots for the current view
  const minPlotArea = st?.minPlotArea ?? 0;
  const onViewChange = useCallback(
    (bbox: [number, number, number, number], zoom: number) => {
      if (mode === "results") return;
      if (zoom < MIN_PARCEL_ZOOM) {
        setParcelInfo((p) => ({ ...p, zoomedOut: true, loading: false, count: 0 }));
        return;
      }
      const id = ++parcelReq.current;
      setParcelInfo((p) => ({ ...p, loading: true, zoomedOut: false, error: null }));
      getParcels(bbox, minPlotArea)
        .then((r) => {
          if (id !== parcelReq.current) return;
          setKnown((prev) => {
            const next = { ...prev };
            for (const f of r.featureCollection.features) next[f.properties.id] = f;
            return next;
          });
          setParcels(r.featureCollection);
          setParcelInfo((p) => ({ ...p, label: r.label, sourceUrl: r.source_url, count: r.count, truncated: r.truncated, loading: false, error: null }));
        })
        .catch((e) => {
          if (id !== parcelReq.current) return;
          setParcelInfo((p) => ({ ...p, loading: false, error: `Cadastral service: ${e.message ?? e}` }));
        });
    },
    [mode, minPlotArea],
  );

  /** parcels currently drawn, plus any selected plot that has scrolled out of view */
  const shownParcels: ParcelFC | null = useMemo(() => {
    const inView = parcels?.features ?? [];
    if (!inView.length && Object.keys(known).length === 0) return null;
    const byId = new Map(inView.map((f) => [f.properties.id, f]));
    for (const id of st?.selected ?? []) {
      const f = known[id];
      if (f && !byId.has(id)) byId.set(id, f);
    }
    return { type: "FeatureCollection", features: [...byId.values()] } as ParcelFC;
  }, [parcels, st?.selected, known]);

  const selectedKey = (st?.selected ?? []).join(",");
  const cropKey = (st?.crops ?? []).join(",");
  useEffect(() => {
    if (mode !== "plan" || !shownParcels || !selectedKey) return;
    const ids = selectedKey.split(",");
    const plots = shownParcels.features
      .filter((f) => ids.includes(f.properties.id))
      .map((f) => ({ id: f.properties.id, name: f.properties.name, geometry: f.geometry, source: f.properties.data_status, registered_area_m2: f.properties.registered_area_m2 }));
    if (!plots.length) return;
    const id = ++siteReq.current;
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (cancelled) return;
      setSiteLoading(true);
      setSiteError(null);
      try {
        const r = await getSiteSummary(plots, cropKey ? cropKey.split(",") : []);
        if (!cancelled && id === siteReq.current) setSite(r);
      } catch (e) {
        if (!cancelled && id === siteReq.current) setSiteError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled && id === siteReq.current) setSiteLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey, cropKey, mode]);

  const runScenario = useCallback(
    async (scenario: string, fresh: boolean) => {
      if (!st || !shownParcels) return;
      const id = ++runRef.current;
      setError(null);
      if (fresh) {
        setRunning(true);
        setStages([]);
        setIters([]);
        setStep(4);
      } else setSwitching(true);
      const req = buildRequest(st, shownParcels, scenario);
      try {
        const r = await optimizeStream(req, (e) => {
          if (id !== runRef.current) return;
          if (e.event === "stage") setStages((s) => (s[s.length - 1] === e.message ? s : [...s, e.message]));
          if (e.event === "iteration") setIters((it) => [...it, { k: e.k, lambda: e.lambda, net_gain: e.net_gain, capex: e.capex, F: e.F, mip_status: e.mip_status, mip_ms: e.mip_ms }]);
        });
        if (id !== runRef.current) return;
        setResults((prev) => (fresh ? { [scenario]: r } : { ...prev, [scenario]: r }));
        setScenarioId(scenario);
        setMode("results");
        if (fresh) {
          const main = [...r.plots].sort((a, b) => b.allocated_m2 - a.allocated_m2)[0];
          setFocus(main ? [main.plot_id] : r.plots.map((p) => p.plot_id));
          setContext({});
          setLoadingScen(true);
          compareScenarios(req)
            .then((c) => id === runRef.current && setResults((prev) => ({ ...c.scenarios, [scenario]: prev[scenario] ?? c.scenarios[scenario] })))
            .catch(() => undefined)
            .finally(() => setLoadingScen(false));
          r.plots.forEach((pl) =>
            getContext(pl.centroid[0], pl.centroid[1])
              .then((c) => {
                if (id !== runRef.current) return;
                const mk = c.data?.nearest_market;
                setContext((prev) => ({ ...prev, [pl.plot_id]: { text: c.available && mk ? `nearest market (OSM) ${mk.name}, ${(mk.distance_m / 1000).toFixed(1)} km straight-line` : "market context unavailable" } }));
              })
              .catch(() => undefined),
          );
        }
        setFitToken((t) => t + 1);
      } catch (e) {
        if (id === runRef.current) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (id === runRef.current) {
          setRunning(false);
          setSwitching(false);
        }
      }
    },
    [st, shownParcels],
  );

  const onScenario = (id: string) => {
    if (results[id]) setScenarioId(id);
    else void runScenario(id, false);
  };

  const result = mode === "results" ? results[scenarioId] : undefined;

  const { pieces, layoutError } = useMemo(() => {
    if (!result || !shownParcels) return { pieces: null as MapPiece[] | null, layoutError: null as string | null };
    try {
      const out: MapPiece[] = [];
      for (const pl of result.plots) {
        const feat = shownParcels.features.find((f) => f.properties.id === pl.plot_id);
        if (!feat) continue;
        const blocks = result.portfolio
          .filter((b) => b.plot_id === pl.plot_id)
          .map((b, i) => ({ id: `${pl.plot_id}-${b.crop}-${b.technique}-${i}`, label: `${b.crop_name} · ${b.technique_name}`, crop: b.crop, technique: b.technique, areaM2: b.area_m2 }));
        if (!blocks.length) continue;
        const lay = layoutPlot(feat.geometry, blocks, pl.access_m2);
        for (const piece of lay.pieces) {
          const b = result.portfolio.find((x) => piece.id.startsWith(`${pl.plot_id}-${x.crop}-${x.technique}-`));
          out.push({ ...piece, plotId: pl.plot_id, cropName: b?.crop_name, techniqueName: b?.technique_name });
        }
      }
      return { pieces: out.length ? out : null, layoutError: null };
    } catch (e) {
      return { pieces: null, layoutError: e instanceof Error ? e.message : String(e) };
    }
  }, [result, shownParcels]);

  const onToggle = useCallback(
    (id: string) => {
      if (mode !== "plan") return;
      setSt((s) => (s ? { ...s, selected: s.selected.includes(id) ? s.selected.filter((x) => x !== id) : [...s.selected, id] } : s));
    },
    [mode],
  );

  const legendTechs = useMemo(() => {
    if (!result || !cat) return [];
    return Array.from(new Set(result.portfolio.map((b) => b.technique))).map((id) => ({ id, name: cat.techniques[id].name }));
  }, [result, cat]);

  const selectedArea = useMemo(
    () => (shownParcels?.features ?? []).filter((f) => st?.selected.includes(f.properties.id)).reduce((s, f) => s + f.properties.area_m2, 0),
    [shownParcels, st?.selected],
  );
  const unresolvedCount = st ? unresolved(missingInputs, st).length : 0;

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-[44px] shrink-0 items-center justify-between border-b border-[var(--line-strong)] bg-[var(--panel)] px-5">
        <div className="flex items-baseline gap-3">
          <span className="text-[15px] font-semibold tracking-tight">FarmFit</span>
          <span className="text-[12px] text-[var(--muted)]">Farm portfolio optimizer · Qatar</span>
        </div>
        <div className="flex items-center gap-4 text-[11.5px] text-[var(--muted)]">
          <span>Live Qatar cadastre</span>
          <span className="num">{st?.selected.length ?? 0} plot{(st?.selected.length ?? 0) === 1 ? "" : "s"}</span>
          {unresolvedCount > 0 && <span style={{ color: "var(--warn)" }}>{unresolvedCount} inputs needed</span>}
          <span className="hidden md:inline">OR-Tools MIP · Dinkelbach · AquaCrop</span>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-[480px] shrink-0 border-r border-[var(--line-strong)] bg-[var(--panel)]">
          {loadError ? (
            <div className="p-5">
              <Notice tone="bad">
                Cannot reach the optimizer service at <span className="num">{API}</span>: {loadError}. Start it with{" "}
                <span className="num">uvicorn app.main:app --port 8000</span> from the backend folder (see README).
              </Notice>
            </div>
          ) : !cat || !st ? (
            <div className="p-5 text-[var(--muted)]">Loading catalog…</div>
          ) : mode === "plan" ? (
            <PlanPanel
              cat={cat}
              missingInputs={missingInputs}
              site={site}
              siteLoading={siteLoading}
              siteError={siteError}
              parcels={shownParcels}
              parcelInfo={parcelInfo}
              st={st}
              set={set}
              step={step}
              setStep={setStep}
              running={running}
              stages={stages}
              iters={iters}
              error={error}
              onRun={() => void runScenario("normal", true)}
              onFit={() => setFitToken((t) => t + 1)}
            />
          ) : (
            <ResultsPanel
              cat={cat}
              scenarioId={scenarioId}
              onScenario={onScenario}
              results={results}
              loadingScenarios={loadingScen}
              switching={switching}
              onEdit={() => {
                setMode("plan");
                setStep(3);
              }}
              context={context}
            />
          )}
        </aside>

        <main className="relative min-w-0 flex-1">
          {exploreReady && (
          <MapView
            initialBounds={explore ? (explore.bbox as [number, number, number, number]) : null}
            parcels={shownParcels}
            selected={mode === "results" && result ? result.plots.map((p) => p.plot_id) : (st?.selected ?? [])}
            onToggle={onToggle}
            onViewChange={onViewChange}
            pieces={pieces}
            fitToken={fitToken}
            fitIds={mode === "results" ? focus : null}
          />
          )}
          <Legend techniques={legendTechs} show={mode === "results" && !!pieces} />

          {mode === "plan" && st && (
            <div className="absolute left-3 top-3 max-w-[430px] border border-[var(--line-strong)] bg-[var(--panel)] text-[12px]">
              <div className="px-3 py-1.5">
                <span className="num">{n0(selectedArea)} m²</span>
                <span className="text-[var(--muted)]"> selected · {parcelInfo.zoomedOut ? "zoom in to load cadastral plots" : "click a plot to select it"}</span>
              </div>
              {explore && (
                <div className="border-t border-[var(--line)] px-3 py-1.5">
                  <button className="flex w-full items-center gap-2 text-left" onClick={() => setShowExplore(!showExplore)}>
                    <span className="inline-block h-1.5 w-1.5 shrink-0" style={{ background: "var(--accent)" }} />
                    <span className="flex-1 text-[11.5px] text-[var(--muted)]">
                      {explore.label} · {explore.window}
                    </span>
                    <span className="text-[11px] text-[var(--faint)]">{showExplore ? "hide" : "why here"}</span>
                  </button>
                  {showExplore && (
                    <div className="mt-1.5 border-t border-[var(--line)] pt-1.5 text-[11px] leading-snug text-[var(--muted)]">
                      <ul className="space-y-0.5">
                        {explore.reasons.map((r, i) => (
                          <li key={i} className="flex gap-1.5"><span className="mt-[6px] inline-block h-[3px] w-[3px] shrink-0 bg-[var(--faint)]" />{r}</li>
                        ))}
                      </ul>
                      <div className="mt-1.5 text-[10.5px] text-[var(--faint)]">
                        Chosen by querying {explore.windows_searched.length} farming municipalities in the live cadastre
                        ({explore.windows_searched.reduce((a, w) => a + w.plots_found, 0).toLocaleString()} plots screened)
                        and ranking clusters on {explore.criteria_used.join(", ").replace(/_/g, " ")}.
                        {explore.criteria_uninformative.length > 0 &&
                          ` ${explore.criteria_uninformative.join(", ").replace(/_/g, " ")} did not vary between candidates and was excluded.`}
                        {" "}No plot is preselected.
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
          {layoutError && <div className="absolute left-3 top-3 max-w-[360px]"><Notice tone="bad">Layout could not be generated: {layoutError}</Notice></div>}
          {mode === "results" && result && (
            <div className="absolute left-3 top-3 flex flex-wrap items-center gap-1 border border-[var(--line-strong)] bg-[var(--panel)] px-3 py-1.5 text-[12px]">
              <span className="font-medium">{result.scenario.name}</span>
              <span className="text-[var(--muted)]">· live cadastral geometry</span>
              <span className="mx-1 text-[var(--line-strong)]">|</span>
              <span className="eyebrow mr-1">Focus</span>
              {result.plots.map((pl) => {
                const on = focus?.length === 1 && focus[0] === pl.plot_id;
                return (
                  <button
                    key={pl.plot_id}
                    className="num mr-1 border px-1.5 text-[11px]"
                    style={{ borderColor: on ? "var(--ink)" : "var(--line-strong)", background: on ? "var(--ink)" : "transparent", color: on ? "#fff" : "var(--ink)" }}
                    onClick={() => {
                      setFocus([pl.plot_id]);
                      setFitToken((t) => t + 1);
                    }}
                  >
                    {pl.plot_id}
                  </button>
                );
              })}
              <button
                className="border border-[var(--line-strong)] px-1.5 text-[11px]"
                onClick={() => {
                  setFocus(result.plots.map((x) => x.plot_id));
                  setFitToken((t) => t + 1);
                }}
              >
                All
              </button>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
