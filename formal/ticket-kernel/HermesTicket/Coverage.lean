import HermesTicket.Interfaces

namespace HermesTicket

/- The exact ten independent severity/blocked groups of the fixed model. -/
def coverageGroups : List (Int × Bool) :=
  [(1, false), (1, true), (2, false), (2, true), (3, false),
   (3, true), (4, false), (4, true), (5, false), (5, true)]

def inGroup (g : Int × Bool) (c : Cell) : Bool :=
  decide (c.severity = g.1 ∧ c.blocked = g.2)

/- Right-fold insertion puts an earlier input occurrence before later equal-lo
   occurrences, so this implements stable sorting by the lower endpoint. -/
def insertCell (c : Cell) : List Cell → List Cell
  | [] => [c]
  | d :: ds => if c.lo ≤ d.lo then c :: d :: ds else d :: insertCell c ds

def sortCells : List Cell → List Cell
  | [] => []
  | c :: cs => insertCell c (sortCells cs)

theorem insertCell_perm (c : Cell) (cs : List Cell) :
    (insertCell c cs).Perm (c :: cs) := by
  induction cs with
  | nil => exact .refl _
  | cons d ds ih =>
    simp only [insertCell]
    split
    · exact .refl _
    · exact (ih.cons d).trans (.swap _ _ _)

theorem sortCells_perm (cs : List Cell) : (sortCells cs).Perm cs := by
  induction cs with
  | nil => exact .refl _
  | cons c cs ih => exact (insertCell_perm c (sortCells cs)).trans (ih.cons c)

def checkChain : List Cell → Int → Bool
  | [], start => start == 87601
  | c :: cs, start => (c.lo == start) && checkChain cs (c.hi + 1)

def checkGroup (cells : List Cell) (g : Int × Bool) : Bool :=
  checkChain (sortCells (cells.filter (inGroup g))) 0

def checkCover (cells : List Cell) : Bool := coverageGroups.all (checkGroup cells)

def containsAge (age : Int) (c : Cell) : Bool := decide (c.lo ≤ age ∧ age ≤ c.hi)

def containsRow (r : Row) (c : Cell) : Bool :=
  decide (c.severity = r.severity ∧ c.blocked = r.blocked ∧
    c.lo ≤ r.age ∧ r.age ≤ c.hi)

theorem validCell_interval {c : Cell} (h : validCell c = true) :
    0 ≤ c.lo ∧ c.lo ≤ c.hi ∧ c.hi ≤ 87600 := by
  simp only [validCell, Bool.and_eq_true, decide_eq_true_eq] at h
  exact ⟨h.1.1.2.2.1, h.1.1.2.2.2.1, h.1.1.2.2.2.2⟩

theorem checkChain_lower (cs : List Cell) (start : Int)
    (hvalid : cs.all validCell = true) (hchain : checkChain cs start = true) :
    ∀ c ∈ cs, start ≤ c.lo := by
  induction cs generalizing start with
  | nil => simp
  | cons c cs ih =>
    simp only [List.all_cons, Bool.and_eq_true] at hvalid
    simp only [checkChain, Bool.and_eq_true, beq_iff_eq] at hchain
    intro d hd
    rcases List.mem_cons.mp hd with h | h
    · subst d
      omega
    · have htail := ih (c.hi + 1) hvalid.2 hchain.2 d h
      have hbounds := validCell_interval hvalid.1
      omega

theorem checkChain_count (cs : List Cell) (start age : Int)
    (hvalid : cs.all validCell = true) (hchain : checkChain cs start = true)
    (hstart : start ≤ age) (hend : age < 87601) :
    cs.countP (containsAge age) = 1 := by
  induction cs generalizing start with
  | nil =>
    simp only [checkChain, beq_iff_eq] at hchain
    omega
  | cons c cs ih =>
    simp only [List.all_cons, Bool.and_eq_true] at hvalid
    simp only [checkChain, Bool.and_eq_true, beq_iff_eq] at hchain
    by_cases hage : age ≤ c.hi
    · have hhead : containsAge age c = true := by
        simp only [containsAge, decide_eq_true_eq]
        exact ⟨by omega, hage⟩
      have hzero : cs.countP (containsAge age) = 0 := by
        apply List.countP_eq_zero.mpr
        intro d hd
        have hlow := checkChain_lower cs (c.hi + 1) hvalid.2 hchain.2 d hd
        simp only [containsAge, decide_eq_true_eq]
        omega
      simp [List.countP_cons, hhead, hzero]
    · have hhead : containsAge age c = false := by
        simp only [containsAge, decide_eq_false_iff_not]
        omega
      have htail := ih (c.hi + 1) hvalid.2 hchain.2 (by omega)
      simp [List.countP_cons, hhead, htail]

theorem validRow_group (r : Row) (hr : validRow r) :
    (r.severity, r.blocked) ∈ coverageGroups := by
  have hs : r.severity = 1 ∨ r.severity = 2 ∨ r.severity = 3 ∨
      r.severity = 4 ∨ r.severity = 5 := by
    unfold validRow at hr
    omega
  cases hb : r.blocked <;> rcases hs with h | h | h | h | h <;>
    simp [coverageGroups, hb, h]

theorem coverage_count (cells : List Cell) (r : Row)
    (hvalid : cells.all validCell = true) (hCover : checkCover cells = true)
    (hr : validRow r) : cells.countP (containsRow r) = 1 := by
  let filtered := cells.filter (inGroup (r.severity, r.blocked))
  let ordered := sortCells filtered
  have hgroup : checkGroup cells (r.severity, r.blocked) = true :=
    List.all_eq_true.mp hCover _ (validRow_group r hr)
  have hvf : filtered.all validCell = true := by
    apply List.all_eq_true.mpr
    intro c hc
    exact List.all_eq_true.mp hvalid c (List.mem_filter.mp hc).1
  have hvo : ordered.all validCell = true := by
    apply List.all_eq_true.mpr
    intro c hc
    exact List.all_eq_true.mp hvf c ((sortCells_perm filtered).mem_iff.mp hc)
  have hcount : ordered.countP (containsAge r.age) = 1 :=
    checkChain_count ordered 0 r.age hvo hgroup hr.2.2.1 (by have := hr.2.2.2; omega)
  have hsorted : filtered.countP (containsAge r.age) = 1 := by
    rw [← (sortCells_perm filtered).countP_eq (containsAge r.age)]
    exact hcount
  have hrow : filtered.countP (containsRow r) = filtered.countP (containsAge r.age) := by
    apply List.countP_congr
    intro c hc
    have hg := (List.mem_filter.mp hc).2
    simp only [inGroup, decide_eq_true_eq] at hg
    simp only [containsRow, containsAge, decide_eq_true_eq, Cell.contains]
    simp [hg.1, hg.2]
  have hfilter : filtered.countP (containsRow r) = cells.countP (containsRow r) := by
    rw [List.countP_filter]
    apply List.countP_congr
    intro c hc
    simp only [Bool.and_eq_true, containsRow, inGroup, decide_eq_true_eq]
    constructor
    · exact fun h => h.1
    · intro h
      exact ⟨h, ⟨h.1, h.2.1⟩⟩
  rw [← hfilter, hrow]
  exact hsorted

/- Indexing original input occurrences avoids the weaker claim that equal Cell
   values are unique. A repeated identical Cell has two distinct indices. -/
def occurrenceAt (cells : List Cell) (r : Row) (i : Nat) : Prop :=
  ∃ c, cells[i]? = some c ∧ c.contains r

private theorem count_one_unique_index {α : Type} (p : α → Bool) (xs : List α)
    (hcount : xs.countP p = 1) :
    ∃ i : Nat, (∃ x, xs[i]? = some x ∧ p x = true) ∧
      ∀ j : Nat, (∃ x, xs[j]? = some x ∧ p x = true) → j = i := by
  induction xs with
  | nil => simp at hcount
  | cons x xs ih =>
    by_cases hp : p x = true
    · have hzero : xs.countP p = 0 := by
        simp only [List.countP_cons, hp, ↓reduceIte] at hcount
        omega
      refine ⟨0, ⟨x, rfl, hp⟩, ?_⟩
      intro j hj
      cases j with
      | zero => rfl
      | succ j =>
        obtain ⟨y, hlookup, hy⟩ := hj
        have hmem : y ∈ xs := List.mem_of_getElem? hlookup
        have hnot := List.countP_eq_zero.mp hzero y hmem
        exact False.elim (hnot hy)
    · have htail : xs.countP p = 1 := by
        simpa [List.countP_cons, hp] using hcount
      obtain ⟨i, ⟨y, hlookup, hy⟩, huniq⟩ := ih htail
      refine ⟨i + 1, ⟨y, hlookup, hy⟩, ?_⟩
      intro j hj
      cases j with
      | zero =>
        obtain ⟨z, hlookup, hz⟩ := hj
        have heq : x = z := Option.some.inj hlookup
        subst z
        exact False.elim (hp hz)
      | succ j =>
        have heq := huniq j hj
        omega

theorem coverage_unique (cells : List Cell) (r : Row)
    (hvalid : cells.all validCell = true) (hCover : checkCover cells = true)
    (hr : validRow r) :
    ∃ i, occurrenceAt cells r i ∧ ∀ j, occurrenceAt cells r j → j = i := by
  have hc := coverage_count cells r hvalid hCover hr
  obtain ⟨i, ⟨c, hlookup, hcontains⟩, huniq⟩ :=
    count_one_unique_index (containsRow r) cells hc
  refine ⟨i, ⟨c, hlookup, ?_⟩, ?_⟩
  · simpa [containsRow, Cell.contains] using hcontains
  · intro j hj
    obtain ⟨d, hlookup, hd⟩ := hj
    apply huniq j
    exact ⟨d, hlookup, by simpa [containsRow, Cell.contains] using hd⟩

theorem coverage_exists (cells : List Cell) (r : Row)
    (hvalid : cells.all validCell = true) (hCover : checkCover cells = true)
    (hr : validRow r) : ∃ c, c ∈ cells ∧ c.contains r := by
  have hc := coverage_count cells r hvalid hCover hr
  have hpos : 0 < cells.countP (containsRow r) := by omega
  obtain ⟨c, hmem, hcontains⟩ := List.countP_pos_iff.mp hpos
  exact ⟨c, hmem, by simpa [containsRow, Cell.contains] using hcontains⟩

end HermesTicket
