"use client";

import { useMemo, useState } from "react";
import type { DataRow, SourceType } from "@/lib/types";
import { TYPE_LABEL, TypeBadge } from "./ui";

function fmt(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Math.abs(v) >= 100 ? v.toLocaleString("en-US", { maximumFractionDigits: 0 }) : String(Number(v.toFixed(3)));
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function split(note: string): [string, string] {
  const m = /^\[([^\]]+)\]\s*(.*)$/.exec(note);
  return m ? [m[1], m[2]] : ["Other", note];
}

function SourceCell({ r }: { r: DataRow }) {
  return (
    <>
      {r.url ? (
        <a className="underline decoration-[var(--line-strong)] underline-offset-2" href={r.url} target="_blank" rel="noreferrer">{r.source}</a>
      ) : (
        r.source
      )}
      {r.status && r.status !== "missing" && <span className="ml-1.5 text-[10.5px] text-[var(--faint)]">{r.status.replaceAll("_", " ")}</span>}
    </>
  );
}

export default function DataPanel({ rows, wide = false }: { rows: DataRow[]; wide?: boolean }) {
  const [type, setType] = useState<SourceType | "all" | "missing">("all");
  const [q, setQ] = useState("");
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: rows.length, missing: rows.filter((r) => r.status === "missing").length };
    for (const r of rows) c[r.type] = (c[r.type] ?? 0) + 1;
    return c;
  }, [rows]);
  const shown = rows.filter(
    (r) =>
      (type === "all" ? true : type === "missing" ? r.status === "missing" : r.type === type) &&
      (q === "" || `${r.label} ${r.source} ${r.note}`.toLowerCase().includes(q.toLowerCase())),
  );
  const groups = useMemo(() => {
    const g: Record<string, DataRow[]> = {};
    for (const r of shown) (g[split(r.note)[0]] ??= []).push(r);
    return g;
  }, [shown]);

  const chips: { id: SourceType | "all" | "missing"; label: string }[] = [
    { id: "all", label: "All" },
    ...(Object.keys(TYPE_LABEL) as SourceType[]).map((t) => ({ id: t, label: TYPE_LABEL[t] })),
    { id: "missing", label: "Missing" },
  ];

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        {chips.map((c) => (
          <button key={c.id} onClick={() => setType(c.id)} className="chip cursor-pointer" style={{ background: type === c.id ? "var(--ink)" : "transparent", color: type === c.id ? "#fff" : "var(--muted)", borderColor: type === c.id ? "var(--ink)" : "var(--line-strong)" }}>
            {c.label} <span className="num">{counts[c.id] ?? 0}</span>
          </button>
        ))}
      </div>
      <input className="field mb-3 !font-sans" placeholder="Search inputs, sources, notes…" value={q} onChange={(e) => setQ(e.target.value)} />
      {Object.entries(groups).map(([g, list]) => (
        <div key={g} className="mb-5">
          <div className="eyebrow mb-1">{g}</div>
          {wide ? (
            <table className="tbl">
              <thead><tr><th>Input</th><th className="r">Value</th><th>Unit</th><th>Source</th><th>Date</th><th>Type</th></tr></thead>
              <tbody>
                {list.map((r) => {
                  const missing = r.status === "missing";
                  return (
                    <tr key={r.key} style={missing ? { background: "#fbf1dd" } : undefined}>
                      <td className="max-w-[420px]"><div className="font-medium">{r.label}</div>{split(r.note)[1] && <div className="text-[11px] leading-snug text-[var(--muted)]">{split(r.note)[1]}</div>}</td>
                      <td className="r num whitespace-nowrap">{missing ? <span style={{ color: "var(--warn)" }}>MISSING</span> : fmt(r.value)}</td>
                      <td className="text-[11.5px] text-[var(--muted)]">{r.unit}</td>
                      <td className="max-w-[340px] text-[11.5px]"><SourceCell r={r} /></td>
                      <td className="num whitespace-nowrap text-[11.5px]">{r.date}</td>
                      <td><TypeBadge type={r.type} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div>
              {list.map((r) => {
                const missing = r.status === "missing";
                const note = split(r.note)[1];
                return (
                  <div key={r.key} className="border-b border-[var(--line)] py-2" style={missing ? { background: "#fbf1dd", paddingLeft: 6, paddingRight: 6 } : undefined}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="font-medium leading-snug">{r.label}</span>
                      <span className="num shrink-0 text-right">
                        {missing ? <span style={{ color: "var(--warn)" }}>MISSING</span> : <>{fmt(r.value)} <span className="text-[11px] text-[var(--muted)]">{r.unit}</span></>}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-[var(--muted)]">
                      <TypeBadge type={r.type} />
                      <span className="num">{r.date}</span>
                      <span className="min-w-0 text-[var(--ink)]"><SourceCell r={r} /></span>
                    </div>
                    {note && <div className="mt-1 text-[11px] leading-snug text-[var(--muted)]">{note}</div>}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ))}
      {shown.length === 0 && <div className="text-[12px] text-[var(--muted)]">Nothing matches.</div>}
    </div>
  );
}
