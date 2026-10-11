import HermesTicket.Interfaces

namespace HermesTicket

theorem affine_add_value (f g : Affine) (age : Int) :
    (f.add g).value age = f.value age + g.value age := by
  simp only [Affine.add, Affine.value, Int.add_mul]
  omega

theorem affine_scale_value (k : Int) (f : Affine) (age : Int) :
    (f.scale k).value age = k * f.value age := by
  simp only [Affine.scale, Affine.value, Int.mul_add, Int.mul_assoc]

theorem affine_sub_value (f g : Affine) (age : Int) :
    (f.sub g).value age = f.value age - g.value age := by
  simp only [Affine.sub, Affine.value, Int.sub_mul]
  omega

/- Bounds use multiplication order explicitly. The coefficients and ages are
   arbitrary integers; in particular negative slopes are permitted. -/
theorem affine_bounds (f : Affine) {lo hi age : Int}
    (hlo : lo ≤ age) (hhi : age ≤ hi) :
    (extrema f lo hi).1 ≤ f.value age ∧
      f.value age ≤ (extrema f lo hi).2 := by
  change min (f.value lo) (f.value hi) ≤ f.value age ∧
    f.value age ≤ max (f.value lo) (f.value hi)
  by_cases hs : 0 ≤ f.slope
  · have hleft : f.value lo ≤ f.value age :=
      Int.add_le_add_right (Int.mul_le_mul_of_nonneg_left hlo hs) f.intercept
    have hright : f.value age ≤ f.value hi :=
      Int.add_le_add_right (Int.mul_le_mul_of_nonneg_left hhi hs) f.intercept
    exact ⟨Int.le_trans (Int.min_le_left _ _) hleft,
      Int.le_trans hright (Int.le_max_right _ _)⟩
  · have hs' : f.slope ≤ 0 := by omega
    have hleft : f.value hi ≤ f.value age :=
      Int.add_le_add_right (Int.mul_le_mul_of_nonpos_left hs' hhi) f.intercept
    have hright : f.value age ≤ f.value lo :=
      Int.add_le_add_right (Int.mul_le_mul_of_nonpos_left hs' hlo) f.intercept
    exact ⟨Int.le_trans (Int.min_le_right _ _) hleft,
      Int.le_trans hright (Int.le_max_left _ _)⟩

theorem equalOnCell_sound (f g : Affine) {lo hi age : Int}
    (hEq : equalOnCell f g lo hi = true)
    (hlo : lo ≤ age) (hhi : age ≤ hi) : f.value age = g.value age := by
  have hext : extrema (f.sub g) lo hi = (0, 0) := by
    simpa only [equalOnCell, beq_iff_eq] using hEq
  have hb := affine_bounds (f.sub g) hlo hhi
  simp only [hext, Prod.fst, Prod.snd] at hb
  have hz : (f.sub g).value age = 0 := Int.le_antisymm hb.2 hb.1
  rw [affine_sub_value] at hz
  omega

theorem referenceAffine_sound (c : Cell) (r : Row) (f : Affine)
    (hRef : referenceAffine c = some f) (hContains : c.contains r) :
    f.value r.age = specScore r := by
  rcases hContains with ⟨hs, hb, hlo, hhi⟩
  by_cases hEarly : c.hi < 168
  · simp only [referenceAffine, hEarly, if_true] at hRef
    have hf := Option.some.inj hRef
    cases hf
    have hAge : r.age ≤ 168 := by omega
    simp only [Affine.value, Int.one_mul, specScore, hs, hb, Int.min_eq_left hAge]
    omega
  · by_cases hLate : c.lo ≥ 168
    · simp only [referenceAffine, hEarly, hLate, if_false, if_true] at hRef
      have hf := Option.some.inj hRef
      cases hf
      have hAge : 168 ≤ r.age := by omega
      simp only [Affine.value, Int.zero_mul, Int.zero_add, specScore, hs, hb,
        Int.min_eq_right hAge]
    · simp only [referenceAffine, hEarly, hLate, if_false] at hRef
      cases hRef

theorem priorityRelation_sound (p : Priority) (f : Affine) {lo hi age : Int}
    (hRel : priorityRelation p f lo hi = true)
    (hlo : lo ≤ age) (hhi : age ≤ hi) : p = businessPriority (f.value age) := by
  have hb := affine_bounds f hlo hhi
  cases p with
  | urgent =>
      have hMin : 500 ≤ (extrema f lo hi).1 := of_decide_eq_true hRel
      have hAge : f.value age ≥ 500 := Int.le_trans hMin hb.1
      simp only [businessPriority, hAge, if_true]
  | high =>
      have hExt : 300 ≤ (extrema f lo hi).1 ∧ (extrema f lo hi).2 < 500 :=
        of_decide_eq_true hRel
      have hLo : f.value age ≥ 300 := Int.le_trans hExt.1 hb.1
      have hHi : ¬f.value age ≥ 500 := by omega
      simp only [businessPriority, hLo, hHi, if_true, if_false]
  | normal =>
      have hExt : (extrema f lo hi).2 < 300 := of_decide_eq_true hRel
      have hLo : ¬f.value age ≥ 300 := by omega
      have hHi : ¬f.value age ≥ 500 := by omega
      simp only [businessPriority, hLo, hHi, if_false]

end HermesTicket
