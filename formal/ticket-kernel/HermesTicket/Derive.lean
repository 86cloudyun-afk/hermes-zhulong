import HermesTicket.Syntax
import HermesTicket.Affine

namespace HermesTicket

/- Context compatibility is required only when score references are legal.
   Concrete score expressions (ctx=false) therefore need no score assumption. -/
def EnvMatches (ctx : Bool) (c : Cell) (scoreAff : Option Affine) (env : Env) : Prop :=
  env.severity = c.severity ∧ env.blocked = c.blocked ∧
  c.lo ≤ env.age ∧ env.age ≤ c.hi ∧
  (ctx = true → ∃ f, scoreAff = some f ∧ env.score = f.value env.age)

mutual
  def deriveI : IExpr ctx → Cell → Option Affine → Option Affine
    | .lit n, _, _ => some ⟨0, n⟩
    | .severity, c, _ => some ⟨0, c.severity⟩
    | .age, _, _ => some ⟨1, 0⟩
    | .score _, _, scoreAff => scoreAff
    | .add first second rest, c, scoreAff => do
        let f ← deriveI first c scoreAff
        let g ← deriveI second c scoreAff
        let t ← deriveTerms rest c scoreAff
        return (f.add g).add t
    | .mul scalar arg, c, scoreAff => do
        let f ← deriveI arg c scoreAff
        return f.scale scalar
    | .min left right, c, scoreAff => do
        let f ← deriveI left c scoreAff
        let g ← deriveI right c scoreAff
        let bounds := extrema (f.sub g) c.lo c.hi
        if bounds.2 ≤ 0 then return f
        else if bounds.1 ≥ 0 then return g
        else none
    | .ite guard yes no, c, scoreAff => do
        let b ← deriveB guard c scoreAff
        if b then deriveI yes c scoreAff else deriveI no c scoreAff
  def deriveB : BExpr ctx → Cell → Option Affine → Option Bool
    | .blocked, c, _ => some c.blocked
    | .ge left right, c, scoreAff => do
        let f ← deriveI left c scoreAff
        let g ← deriveI right c scoreAff
        let bounds := extrema (f.sub g) c.lo c.hi
        if bounds.1 ≥ 0 then return true
        else if bounds.2 < 0 then return false
        else none
  def deriveTerms : Terms ctx → Cell → Option Affine → Option Affine
    | .nil, _, _ => some Affine.zero
    | .cons head tail, c, scoreAff => do
        let f ← deriveI head c scoreAff
        let t ← deriveTerms tail c scoreAff
        return f.add t
end

def deriveP : PExpr → Cell → Option Affine → Option Priority
  | .lit priority, _, _ => some priority
  | .ite guard yes no, c, scoreAff => do
      let b ← deriveB guard c scoreAff
      if b then deriveP yes c scoreAff else deriveP no c scoreAff

mutual
  theorem deriveI_sound (e : IExpr ctx) (c : Cell) (scoreAff : Option Affine)
      (f : Affine) (env : Env) (h : deriveI e c scoreAff = some f)
      (henv : EnvMatches ctx c scoreAff env) : evalI e env = f.value env.age := by
    cases e with
    | lit n =>
        simp only [deriveI, Option.some.injEq] at h
        subst f
        simp [evalI, Affine.value]
    | severity =>
        simp only [deriveI, Option.some.injEq] at h
        subst f
        simpa [evalI, Affine.value] using henv.1
    | age =>
        simp only [deriveI, Option.some.injEq] at h
        subst f
        simp [evalI, Affine.value]
    | score allowed =>
        obtain ⟨g, hg, heq⟩ := henv.2.2.2.2 allowed
        have hfg : g = f := by simpa [deriveI, hg] using h
        simpa [evalI, hfg] using heq
    | add first second rest =>
        simp only [deriveI, bind, Option.bind_eq_some, pure, Option.some.injEq] at h
        obtain ⟨a, ha, b, hb, t, ht, hout⟩ := h
        subst f
        simp only [evalI, deriveI_sound first c scoreAff a env ha henv,
          deriveI_sound second c scoreAff b env hb henv,
          deriveTerms_sound rest c scoreAff t env ht henv, affine_add_value]
    | mul scalar arg =>
        simp only [deriveI, bind, Option.bind_eq_some, pure, Option.some.injEq] at h
        obtain ⟨a, ha, hout⟩ := h
        subst f
        simp only [evalI, deriveI_sound arg c scoreAff a env ha henv, affine_scale_value]
    | min left right =>
        simp only [deriveI, bind, Option.bind_eq_some] at h
        obtain ⟨a, ha, b, hb, hout⟩ := h
        have hleft := deriveI_sound left c scoreAff a env ha henv
        have hright := deriveI_sound right c scoreAff b env hb henv
        have hbounds := affine_bounds (a.sub b) henv.2.2.1 henv.2.2.2.1
        rw [affine_sub_value] at hbounds
        by_cases hchoose : (extrema (a.sub b) c.lo c.hi).2 ≤ 0
        · simp only [hchoose, if_true, pure, Option.some.injEq] at hout
          subst f
          have hle : a.value env.age ≤ b.value env.age := by omega
          simp only [evalI, hleft, hright, Int.min_eq_left hle]
        · by_cases hchoose' : (extrema (a.sub b) c.lo c.hi).1 ≥ 0
          · simp only [hchoose, hchoose', if_false, if_true, pure, Option.some.injEq] at hout
            subst f
            have hle : b.value env.age ≤ a.value env.age := by omega
            simp only [evalI, hleft, hright, Int.min_eq_right hle]
          · simp [hchoose, hchoose'] at hout
    | ite guard yes no =>
        simp only [deriveI, bind, Option.bind_eq_some] at h
        obtain ⟨b, hb, hout⟩ := h
        have hguard := deriveB_sound guard c scoreAff b env hb henv
        cases b with
        | false =>
            simp only [Bool.false_eq_true, ↓reduceIte] at hout
            simpa only [evalI, hguard, Bool.false_eq_true, ↓reduceIte] using
              deriveI_sound no c scoreAff f env hout henv
        | true =>
            simp only [↓reduceIte] at hout
            simpa only [evalI, hguard, ↓reduceIte] using
              deriveI_sound yes c scoreAff f env hout henv
  termination_by structural e

  theorem deriveB_sound (e : BExpr ctx) (c : Cell) (scoreAff : Option Affine)
      (b : Bool) (env : Env) (h : deriveB e c scoreAff = some b)
      (henv : EnvMatches ctx c scoreAff env) : evalB e env = b := by
    cases e with
    | blocked =>
        simp only [deriveB, Option.some.injEq] at h
        subst b
        exact henv.2.1
    | ge left right =>
        simp only [deriveB, bind, Option.bind_eq_some] at h
        obtain ⟨a, ha, t, ht, hout⟩ := h
        have hleft := deriveI_sound left c scoreAff a env ha henv
        have hright := deriveI_sound right c scoreAff t env ht henv
        have hbounds := affine_bounds (a.sub t) henv.2.2.1 henv.2.2.2.1
        rw [affine_sub_value] at hbounds
        by_cases hchoose : (extrema (a.sub t) c.lo c.hi).1 ≥ 0
        · simp only [hchoose, if_true, pure, Option.some.injEq] at hout
          subst b
          have hge : a.value env.age ≥ t.value env.age := by omega
          simp only [evalB, hleft, hright, hge, decide_true]
        · by_cases hchoose' : (extrema (a.sub t) c.lo c.hi).2 < 0
          · simp only [hchoose, hchoose', if_false, if_true, pure, Option.some.injEq] at hout
            subst b
            have hnge : ¬a.value env.age ≥ t.value env.age := by omega
            simp only [evalB, hleft, hright, hnge, decide_false]
          · simp [hchoose, hchoose'] at hout
  termination_by structural e

  theorem deriveTerms_sound (terms : Terms ctx) (c : Cell) (scoreAff : Option Affine)
      (f : Affine) (env : Env) (h : deriveTerms terms c scoreAff = some f)
      (henv : EnvMatches ctx c scoreAff env) : evalTerms terms env = f.value env.age := by
    cases terms with
    | nil =>
        simp only [deriveTerms, Option.some.injEq] at h
        subst f
        simp [evalTerms, Affine.zero, Affine.value]
    | cons head tail =>
        simp only [deriveTerms, bind, Option.bind_eq_some, pure, Option.some.injEq] at h
        obtain ⟨a, ha, t, ht, hout⟩ := h
        subst f
        simp only [evalTerms, deriveI_sound head c scoreAff a env ha henv,
          deriveTerms_sound tail c scoreAff t env ht henv, affine_add_value]
  termination_by structural terms
end

theorem deriveP_sound (e : PExpr) (c : Cell) (scoreAff : Option Affine)
    (p : Priority) (env : Env) (h : deriveP e c scoreAff = some p)
    (henv : EnvMatches true c scoreAff env) : evalP e env = p := by
  cases e with
  | lit priority =>
      simp only [deriveP, Option.some.injEq] at h
      exact h
  | ite guard yes no =>
      simp only [deriveP, bind, Option.bind_eq_some] at h
      obtain ⟨b, hb, hout⟩ := h
      have hguard := deriveB_sound guard c scoreAff b env hb henv
      cases b with
      | false =>
          simp only [Bool.false_eq_true, ↓reduceIte] at hout
          simpa only [evalP, hguard, Bool.false_eq_true, ↓reduceIte] using
            deriveP_sound no c scoreAff p env hout henv
      | true =>
          simp only [↓reduceIte] at hout
          simpa only [evalP, hguard, ↓reduceIte] using
            deriveP_sound yes c scoreAff p env hout henv
termination_by structural e

/- One auditable name collects every sort of the general derivation theorem. -/
theorem derive_sound :
    (∀ (ctx : Bool) (e : IExpr ctx) (c : Cell) (scoreAff : Option Affine)
      (f : Affine) (env : Env), deriveI e c scoreAff = some f →
        EnvMatches ctx c scoreAff env → evalI e env = f.value env.age) ∧
    (∀ (ctx : Bool) (e : BExpr ctx) (c : Cell) (scoreAff : Option Affine)
      (b : Bool) (env : Env), deriveB e c scoreAff = some b →
        EnvMatches ctx c scoreAff env → evalB e env = b) ∧
    (∀ (ctx : Bool) (terms : Terms ctx) (c : Cell) (scoreAff : Option Affine)
      (f : Affine) (env : Env), deriveTerms terms c scoreAff = some f →
        EnvMatches ctx c scoreAff env → evalTerms terms env = f.value env.age) ∧
    (∀ (e : PExpr) (c : Cell) (scoreAff : Option Affine)
      (p : Priority) (env : Env), deriveP e c scoreAff = some p →
        EnvMatches true c scoreAff env → evalP e env = p) :=
  ⟨fun _ => deriveI_sound, fun _ => deriveB_sound,
    fun _ => deriveTerms_sound, deriveP_sound⟩

/- Kernel reduction witnesses cover derivative discontinuities, negative
   slopes, ordered ties and all operands of a genuine n-ary addition. -/
private def edgeCell (lo hi : Int) : Cell := ⟨1, false, lo, hi, ⟨0, 0⟩, .normal⟩

theorem negative_slope_ge_false :
    deriveB (.ge (.mul (-1) .age) (.lit 0) : BExpr false) (edgeCell 1 10) none =
      some false := rfl

theorem negative_slope_min_left :
    deriveI (.min (.mul (-1) .age) (.lit 0) : IExpr false) (edgeCell 1 10) none =
      some ⟨-1, 0⟩ := rfl

theorem crossing_ge_reject :
    deriveB (.ge .age (.lit 168) : BExpr false) (edgeCell 167 168) none = none := rfl

theorem before_boundary_ge_false :
    deriveB (.ge .age (.lit 168) : BExpr false) (edgeCell 0 167) none = some false := rfl

theorem singleton_boundary_ge_true :
    deriveB (.ge .age (.lit 168) : BExpr false) (edgeCell 168 168) none = some true := rfl

theorem min_singleton_tie_left :
    deriveI (.min .age (.lit 168) : IExpr false) (edgeCell 168 168) none =
      some ⟨1, 0⟩ := rfl

theorem nary_derive_every_operand :
    deriveI (.add .age (.lit 7) (.cons (.mul (-2) .age) (.cons (.lit 11) .nil)) :
      IExpr false) (edgeCell 1 10) none = some ⟨-1, 18⟩ := rfl

theorem nary_eval_every_operand :
    evalI (.add .age (.lit 7) (.cons (.mul (-2) .age) (.cons (.lit 11) .nil)) :
      IExpr false) ⟨1, 5, false, 0⟩ = 13 := rfl

theorem cached_score_priority :
    deriveP (.ite (.ge (.score rfl) (.lit 500)) (.lit .urgent) (.lit .normal))
      (edgeCell 0 10) (some ⟨0, 500⟩) = some .urgent := rfl

end HermesTicket
