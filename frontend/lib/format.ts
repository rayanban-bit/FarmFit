const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

export const n0 = (v: number | null | undefined) => (v == null || !isFinite(v) ? "—" : nf0.format(v));
export const n1 = (v: number | null | undefined) => (v == null || !isFinite(v) ? "—" : nf1.format(v));
export const n2 = (v: number | null | undefined) => (v == null || !isFinite(v) ? "—" : nf2.format(v));
export const pct = (v: number | null | undefined, d = 0) => (v == null || !isFinite(v) ? "—" : `${(v * 100).toFixed(d)}%`);
export const qar = (v: number | null | undefined) => (v == null || !isFinite(v) ? "—" : `QAR ${nf0.format(v)}`);
export const years = (v: number | null | undefined) => (v == null ? "Never" : `${nf1.format(v)} yr`);
export const signed = (v: number | null | undefined, f: (x: number) => string = n0) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${f(Math.abs(v))}`);

export const TECH_COLOR: Record<string, string> = {
  open_field: "#a8892f",
  greenhouse: "#2f7d68",
  hydroponic_greenhouse: "#2d6796",
  vertical_hydroponics: "#7d4d8f",
};
export const TECH_ORDER = ["greenhouse", "hydroponic_greenhouse", "vertical_hydroponics", "open_field"];
export const ACCESS_COLOR = "#8d8d86";
export const RESERVE_COLOR = "#c9c6bb";
export const qarKg = (v: number) => `QAR ${v.toFixed(2)}/kg`;
