"use client";

import type { ReactNode } from "react";
import type { SourceType } from "@/lib/types";

export const TYPE_LABEL: Record<SourceType, string> = {
  official_qatar: "Official Qatar data",
  official_dataset: "Official dataset",
  scientific_model: "Scientific model",
  peer_reviewed: "Peer-reviewed research",
  open_dataset: "Open dataset",
  vendor_data: "Vendor data",
  user_supplied: "User supplied",
  unverified: "Estimate",
};

const TYPE_STYLE: Record<SourceType, { bg: string; fg: string; bd: string }> = {
  official_qatar: { bg: "#dce9e3", fg: "#14483b", bd: "#a8c4b9" },
  official_dataset: { bg: "#e4ede9", fg: "#1f5c4d", bd: "#b9cfc6" },
  scientific_model: { bg: "#e5ebf3", fg: "#2d5580", bd: "#bccbe0" },
  peer_reviewed: { bg: "#e3e9f5", fg: "#33417d", bd: "#bcc5e2" },
  open_dataset: { bg: "#eae7f1", fg: "#5a4680", bd: "#cfc7de" },
  vendor_data: { bg: "#efeade", fg: "#5d4a22", bd: "#d3c8ae" },
  user_supplied: { bg: "#fff", fg: "#1b1e1c", bd: "#1b1e1c" },
  unverified: { bg: "#f4ecd9", fg: "#86560f", bd: "#dcc79b" },
};

export function TypeBadge({ type, label }: { type: SourceType; label?: string }) {
  const s = TYPE_STYLE[type];
  return (
    <span className="chip" style={{ background: s.bg, color: s.fg, borderColor: s.bd }}>
      {label ?? TYPE_LABEL[type]}
    </span>
  );
}

export function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-b border-[var(--line)] px-5 py-4">
      <div className="mb-2.5 flex items-baseline justify-between gap-3">
        <h3 className="h-section">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: ReactNode; tone?: "good" | "bad" }) {
  return (
    <div className="border-l-2 border-[var(--line-strong)] pl-3">
      <div className="eyebrow">{label}</div>
      <div className="num mt-0.5 text-[20px] font-medium leading-tight" style={{ color: tone === "bad" ? "var(--bad)" : undefined }}>
        {value}
      </div>
      {sub ? <div className="mt-0.5 text-[11px] text-[var(--muted)]">{sub}</div> : null}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "bad"; children: ReactNode }) {
  const st =
    tone === "warn"
      ? { bg: "var(--warn-soft)", bd: "#dcc79b", fg: "#5f3d08" }
      : tone === "bad"
        ? { bg: "#f6e4e4", bd: "#dfb2b2", fg: "#6d2020" }
        : { bg: "#efede5", bd: "var(--line-strong)", fg: "var(--ink)" };
  return (
    <div className="border px-3 py-2 text-[12px] leading-snug" style={{ background: st.bg, borderColor: st.bd, color: st.fg }}>
      {children}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, disabled }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <div className="inline-flex border border-[var(--line-strong)]">
      {options.map((o, i) => (
        <button
          key={o.id}
          disabled={disabled}
          onClick={() => onChange(o.id)}
          className="h-[28px] px-3 text-[12px] font-medium disabled:opacity-50"
          style={{
            background: value === o.id ? "var(--ink)" : "var(--panel)",
            color: value === o.id ? "#fff" : "var(--ink)",
            borderLeft: i ? "1px solid var(--line-strong)" : undefined,
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
