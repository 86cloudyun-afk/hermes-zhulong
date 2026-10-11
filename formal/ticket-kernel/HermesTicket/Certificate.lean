import HermesTicket.Derive
import HermesTicket.Coverage

namespace HermesTicket

/- This computed checker is a typed model of the pinned Python algorithm.
   Raw-byte parsing, tuple conversion, exception/status behavior, and source
   correspondence are deliberately not premises or results of its theorem. -/
def checkCell (p : Program) (c : Cell) : Bool :=
  match deriveI p.score c none, referenceAffine c with
  | some score, some reference =>
      equalOnCell score reference c.lo c.hi &&
      equalOnCell score c.witness c.lo c.hi &&
      (match deriveP p.priority c (some score) with
       | some priority =>
           priorityRelation priority reference c.lo c.hi && decide (priority = c.priority)
       | none => false)
  | _, _ => false

def checkTyped (p : Program) (cells : List Cell) : Bool :=
  wfProgram p && decide (cells.length ≤ 512) && cells.all validCell &&
  checkCover cells && cells.all (checkCell p)

theorem checkCell_sound (p : Program) (c : Cell) (r : Row)
    (hcheck : checkCell p c = true) (hcontains : c.contains r) :
    evalScore p r = specScore r ∧
      evalRowPriority p r = businessPriority (specScore r) := by
  cases hs : deriveI p.score c none with
  | none => simp [checkCell, hs] at hcheck
  | some score =>
      cases href : referenceAffine c with
      | none => simp [checkCell, hs, href] at hcheck
      | some reference =>
          cases hp : deriveP p.priority c (some score) with
          | none => simp [checkCell, hs, href, hp] at hcheck
          | some priority =>
              simp only [checkCell, hs, href, hp, Bool.and_eq_true,
                decide_eq_true_eq] at hcheck
              have henvScore : EnvMatches false c none
                  ⟨r.severity, r.age, r.blocked, 0⟩ := by
                exact ⟨hcontains.1.symm, hcontains.2.1.symm,
                  hcontains.2.2.1, hcontains.2.2.2, by intro h; contradiction⟩
              have hscore : evalScore p r = score.value r.age :=
                deriveI_sound p.score c none score
                  ⟨r.severity, r.age, r.blocked, 0⟩ hs henvScore
              have hequal : score.value r.age = reference.value r.age :=
                equalOnCell_sound score reference hcheck.1.1
                  hcontains.2.2.1 hcontains.2.2.2
              have hreference : reference.value r.age = specScore r :=
                referenceAffine_sound c r reference href hcontains
              have henvPriority : EnvMatches true c (some score)
                  ⟨r.severity, r.age, r.blocked, evalScore p r⟩ := by
                exact ⟨hcontains.1.symm, hcontains.2.1.symm,
                  hcontains.2.2.1, hcontains.2.2.2, by
                    intro _
                    exact ⟨score, rfl, hscore⟩⟩
              have hpriority : evalRowPriority p r = priority :=
                deriveP_sound p.priority c (some score) priority
                  ⟨r.severity, r.age, r.blocked, evalScore p r⟩ hp henvPriority
              have hbusiness : priority = businessPriority (reference.value r.age) :=
                priorityRelation_sound priority reference hcheck.2.1
                  hcontains.2.2.1 hcontains.2.2.2
              exact ⟨hscore.trans (hequal.trans hreference), by
                rw [hpriority, hbusiness, hreference]⟩

/- The only substantive premise is the result of the computable checker.
   The row quantification covers the complete supported integer domain. -/
theorem rowCertificateSound (p : Program) (cells : List Cell)
    (hcheck : checkTyped p cells = true) (r : Row) (hr : validRow r) :
    evalScore p r = specScore r ∧
      evalRowPriority p r = businessPriority (specScore r) := by
  simp only [checkTyped, Bool.and_eq_true, decide_eq_true_eq] at hcheck
  obtain ⟨c, hmem, hcontains⟩ :=
    coverage_exists cells r hcheck.1.1.2 hcheck.1.2 hr
  exact checkCell_sound p c r (List.all_eq_true.mp hcheck.2 c hmem) hcontains

theorem accepted_coverage_unique (p : Program) (cells : List Cell)
    (hcheck : checkTyped p cells = true) (r : Row) (hr : validRow r) :
    ∃ i, occurrenceAt cells r i ∧ ∀ j, occurrenceAt cells r j → j = i := by
  simp only [checkTyped, Bool.and_eq_true, decide_eq_true_eq] at hcheck
  exact coverage_unique cells r hcheck.1.1.2 hcheck.1.2 hr

theorem accepted_resources (p : Program) (cells : List Cell)
    (hcheck : checkTyped p cells = true) :
    wfProgram p = true ∧ cells.length ≤ 512 ∧ cells.all validCell = true := by
  simp only [checkTyped, Bool.and_eq_true, decide_eq_true_eq] at hcheck
  exact ⟨hcheck.1.1.1.1, hcheck.1.1.1.2, hcheck.1.1.2⟩

theorem accepted_score_businessPriority (p : Program) (cells : List Cell)
    (hcheck : checkTyped p cells = true) (r : Row) (hr : validRow r) :
    evalRowPriority p r = businessPriority (evalScore p r) := by
  obtain ⟨hscore, hpriority⟩ := rowCertificateSound p cells hcheck r hr
  rw [hscore]
  exact hpriority

end HermesTicket
