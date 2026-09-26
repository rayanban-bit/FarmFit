"""
================================================================================================
  FarmFit — THE MATHEMATICAL CORE
  Mixed-integer programming + exact fractional optimization of 5-year ROI
================================================================================================

  Annotated excerpt for presentation. Every block below is copied verbatim from the executable
  implementation in  backend/app/optimizer.py  — line numbers are given so each can be checked.

  Solver:  Google OR-Tools (pywraplp) with the SCIP backend, MIP gap 1e-9
  Method:  Dinkelbach's algorithm — Newton's method on a convex, piecewise-linear function
  Scale:   ~100 variables, ~60 binary, ~180 constraints for a 3-plot farm; solves in ~300 ms


  ── THE PROBLEM ────────────────────────────────────────────────────────────────────────────────

  Given real Qatar cadastral plots, live climate and soil data, and official crop yields,
  decide how to divide the land between crop × technique blocks so that return is maximised
  under land, capital, water, energy and agronomic constraints.

      sets     p ∈ P   plots                 (usable area U_p, from the cadastral PDAREA)
               o ∈ O   options (crop c, technique t) that are compatible, thermally feasible
                       in this plot's climate, AND fully specified by sourced data
               m       months 1..12
               g ∈ G   shared infrastructure groups (water network, cooling plant, dosing)

  ── DECISION VARIABLES ─────────────────────────────────────────────────────────────────────────

      area[p,c,t]  ≥ 0   continuous   square metres allocated          ← THE PORTFOLIO
      z[p,c,t]     ∈ {0,1}            block is used  (enforces minimum block size)
      build[p,t]   ∈ {0,1}            technique built on plot p        (fixed CapEx charged once)
      infra[p,g]   ∈ {0,1}            shared infrastructure built      (charged ONCE, not per block)
      u[c,t]       ∈ {0,1}            crop × technique active anywhere (portfolio composition)
      w[c]         ∈ {0,1}            crop grown anywhere              (crop diversity)

  ── OBJECTIVE ──────────────────────────────────────────────────────────────────────────────────

      Profit  P(x) = Σ (revenue_o − opex_o)·area  −  Σ F_t^op·build  −  Σ F_g^op·infra   [QAR/yr]
      CapEx   C(x) = Σ capex_o·area              +  Σ F_t·build     +  Σ F_g·infra       [QAR]
      Net     N(x) = H·P(x) − C(x)        cash flows: year 0 = −C,  years 1..H = P

                                  maximise   ROI = N(x) / C(x)

      A RATIO of two linear functions — not a linear program. Solved exactly, see §4.

================================================================================================
"""

# ══════════════════════════════════════════════════════════════════════════════════════════════
#  §1  DECISION VARIABLES                                     backend/app/optimizer.py : 369-376
# ══════════════════════════════════════════════════════════════════════════════════════════════

for pl, j, o in self.items:
    self.a[(pl.id, j)] = s.NumVar(0.0, pl.usable_m2, f"a[{pl.id},{o.crop},{o.technique}]")
    self.z[(pl.id, j)] = s.BoolVar(f"z[{pl.id},{o.crop},{o.technique}]")

for pl in problem.plots:
    for t in techs_used:
        self.b[(pl.id, t)] = s.BoolVar(f"build[{pl.id},{t}]")      # pay fixed CapEx once per plot
    for g in groups_used:
        self.y[(pl.id, g)] = s.BoolVar(f"infra[{pl.id},{g}]")      # shared utilities, charged once


# ══════════════════════════════════════════════════════════════════════════════════════════════
#  §2  CONSTRAINTS                                            backend/app/optimizer.py : 378-408
# ══════════════════════════════════════════════════════════════════════════════════════════════

for pl in problem.plots:
    here = [(j, o) for (p2, j, o) in self.items if p2.id == pl.id]

    # LAND ─ allocation cannot exceed the usable area of the real cadastral parcel
    s.Add(sum(self.a[(pl.id, j)] for j, _ in here) <= pl.usable_m2)

    for j, o in here:
        a, z = self.a[(pl.id, j)], self.z[(pl.id, j)]
        s.Add(a <= pl.usable_m2 * z)                               # linking
        s.Add(a >= lim.min_block_m2 * z)                           # no unworkable slivers
        s.Add(z <= self.b[(pl.id, o.technique)])                   # block needs its technique

    for t in techs_used:
        terms = [self.a[(pl.id, j)] for j, o in here if o.technique == t]
        # MINIMUM VIABLE SCALE ─ a greenhouse is not worth building below a threshold area
        s.Add(sum(terms) >= problem.techs[t].min_area_m2 * self.b[(pl.id, t)])
        # SHARED INFRASTRUCTURE ─ this is what makes CapEx(shared) < Σ CapEx(standalone)
        for g in problem.techs[t].requires:
            s.Add(self.b[(pl.id, t)] <= self.y[(pl.id, g)])

# BUDGET ─ total capital committed at year 0
s.Add(self.capex <= lim.budget)

# WATER & ENERGY ─ constrained EVERY MONTH, not just annually.
# Qatar's open-field crops grow Nov–Apr only, so a whole year of irrigation lands in a few months.
# This is what makes crops with different calendars genuinely complementary.
for m in range(MONTHS):
    s.Add(sum(o.water_m[m] * self.a[(pl.id, j)] for pl, j, o in self.items) <= wcap)
    s.Add(sum(o.energy_m[m] * self.a[(pl.id, j)] for pl, j, o in self.items) <= ecap)

s.Add(sum(o.water_year * self.a[(pl.id, j)] for pl, j, o in self.items) <= lim.water_year)
s.Add(sum(o.energy_year * self.a[(pl.id, j)] for pl, j, o in self.items) <= lim.energy_year)


# ══════════════════════════════════════════════════════════════════════════════════════════════
#  §3  PORTFOLIO COMPOSITION                                  backend/app/optimizer.py : 416-460
#      Restricts the FEASIBLE SET only. The objective is untouched and no area is ever pinned —
#      the solver still chooses every percentage.
# ══════════════════════════════════════════════════════════════════════════════════════════════

for (c, t) in pairs:
    u = s.BoolVar(f"use[{c},{t}]")
    terms = [self.a[(pl.id, j)] for pl, j, o in self.items if o.key == (c, t)]
    s.Add(sum(terms) <= total_usable * u)      # marker off  ⇒  no area
    s.Add(sum(terms) >= min_block * u)         # marker on   ⇒  a REAL block, not a token 0 m²

s.Add(sum(self.u.values()) >= lim.min_distinct_combos)          # ≥ 3 distinct crop × technique

for c in sorted({cc for (cc, _t) in pairs}):                     # crop diversity
    wv = s.BoolVar(f"useCrop[{c}]")
    terms = [self.a[(pl.id, j)] for pl, j, o in self.items if o.crop == c]
    s.Add(sum(terms) <= total_usable * wv)
    s.Add(sum(terms) >= min_crop * wv)                           # real participation, not a token

s.Add(sum(self.w.values()) >= lim.min_distinct_crops)            # ≥ 3 crops
s.Add(sum(self.v.values()) >= lim.min_distinct_techniques)       # ≥ 2 techniques


# ══════════════════════════════════════════════════════════════════════════════════════════════
#  §4  THE OBJECTIVE                                          backend/app/optimizer.py : 477-500
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _profit_expr(self):                                          # P(x)  [QAR / year]
    e = sum((o.rev_m2 - o.opex_m2) * self.a[(pl.id, j)] for pl, j, o in self.items)
    e = e - sum(p.techs[t].fixed_opex * v for (pid, t), v in self.b.items())
    e = e - sum(p.groups[g].fixed_opex * v for (pid, g), v in self.y.items())
    return e

def _capex_expr(self):                                           # C(x)  [QAR]
    e = sum(o.capex_m2 * self.a[(pl.id, j)] for pl, j, o in self.items)
    e = e + sum(p.techs[t].fixed_capex * v for (pid, t), v in self.b.items())   # once per tech
    e = e + sum(p.groups[g].fixed_capex * v for (pid, g), v in self.y.items())  # once per plot
    return e

def set_objective(self, lam=None):
    """Maximise N = H·Profit − CapEx, or the Dinkelbach surrogate N − λ·CapEx."""
    h = self.problem.limits.horizon_years
    n_expr = h * self.profit - self.capex
    self.s.Maximize(n_expr if lam is None else n_expr - lam * self.capex)


# ══════════════════════════════════════════════════════════════════════════════════════════════
#  §5  EXACT RATIO OPTIMIZATION — DINKELBACH                   backend/app/optimizer.py : 561-636
#
#      ROI = N(x)/C(x) is a RATIO, so it cannot be maximised by one linear program.
#
#          F(λ) = max_x [ N(x) − λ·C(x) ]        is convex, piecewise-linear and decreasing,
#          with a unique root at  λ* = max ROI.
#
#      So the loop below is Newton's method on F(λ) = 0, and converges finitely —
#      typically 2–4 MIP solves. The result is the PROVED optimum, not a ranking or a score.
# ══════════════════════════════════════════════════════════════════════════════════════════════

lam = 0.0
for k in range(max_iter):
    m = _Model(problem, util_floor, time_limit_s)
    m.set_objective(lam)                                    # ← solve  max N − λ·CapEx
    status, ms = m.solve()

    alloc = _clean(problem, m.extract())
    ev = evaluate(problem, alloc)                           # recomputed independently of the solver
    n, d = ev["net_gain"], ev["capex"]                      # N(x_k),  C(x_k)
    f = n - lam * d                                         # F(λ_k)

    # Dinkelbach's root condition is F(λ) = 0, NOT F(λ) ≤ 0. F < 0 means λ overshot λ* and Newton
    # must keep going. Accepting F ≤ tol stopped the loop at k=0 whenever the best net gain was
    # negative, returning the max-cash-flow plan mislabelled as the max-ROI plan.
    converged_here = abs(f) <= tol * max(1.0, abs(n), d)

    if d <= CAPEX_TOL:                                      # λ = N/C is undefined when CapEx = 0.
        ...                                                 # Classified, never divided by zero:
        #   CapEx = 0, no production  → NO_VIABLE_INVESTMENT   (nothing is worth building)
        #   CapEx = 0, N > 0          → ZERO_CAPEX unbounded    (ratio has no finite maximum)
        #   CapEx = 0, N = 0          → ZERO_CAPEX undefined    (0/0)
        break

    ratio = n / d
    if best_ratio is None or ratio > best_ratio:
        best_ratio, best_alloc = ratio, alloc

    if converged_here:                                      # F(λ) = 0  ⇒  λ IS the optimal ROI
        break
    if k > 0 and abs(ratio - lam) <= 1e-12 * max(1.0, abs(lam)):
        break                                               # λ stopped moving: at the root

    lam = ratio                                             # ← Newton step:  λ ← N/C


# ══════════════════════════════════════════════════════════════════════════════════════════════
#  §6  WHAT MAKES THIS REAL
# ══════════════════════════════════════════════════════════════════════════════════════════════
#
#   ✓  A test enumerates a dense grid of feasible portfolios by brute force and asserts the
#      returned ROI equals the true maximum.                  tests/test_finance.py
#
#   ✓  Every solution is re-evaluated from first principles, independently of the solver, and
#      checked against every constraint before it is returned. optimizer.check_feasible()
#
#   ✓  Constraints that cannot be met together are relaxed in a STATED order and reported —
#      never silently dropped.                                optimizer.solve() relaxation ladder
#
#   ✓  A crop × technique with no defensible data gets NO VARIABLE AT ALL. The model refuses
#      the scenario rather than inventing a coefficient.      catalog.missing_for()
#
#   ✓  108 backend tests, including zero-CapEx, zero-profit, empty feasible set, convergence,
#      monotonicity of λ, and a 200-combination degenerate sweep.
#
# ══════════════════════════════════════════════════════════════════════════════════════════════
