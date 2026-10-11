import HermesTicket.Certificate

namespace HermesTicket

/- The typed transcription of the public sample. Terms contributes the third
   operand to the same n-ary add node. -/
def sampleProgram : Program :=
  ⟨.add (.mul 100 .severity) (.min .age (.lit 168))
      (.cons (.ite .blocked (.lit 50) (.lit 0)) .nil),
    .ite (.ge (.score rfl) (.lit 500)) (.lit .urgent)
      (.ite (.ge (.score rfl) (.lit 300)) (.lit .high) (.lit .normal))⟩

/- A different AST has negative intermediate coefficients, exact cancellation,
   and an extra zero operand; every operand must actually be derived. -/
def alternateProgram : Program :=
  ⟨.add (.mul (-1) (.mul (-100) .severity)) (.min .age (.lit 168))
      (.cons (.ite .blocked (.lit 50) (.lit 0))
        (.cons (.mul (-2) .age) (.cons (.mul 2 .age) (.cons (.lit 0) .nil)))),
    sampleProgram.priority⟩

/- In the exact order and with the exact values of the public 26-cell JSON. -/
def sampleCells : List Cell :=
  [⟨1, false, 0, 167, ⟨1, 100⟩, .normal⟩,
   ⟨1, false, 168, 87600, ⟨0, 268⟩, .normal⟩,
   ⟨1, true, 0, 149, ⟨1, 150⟩, .normal⟩,
   ⟨1, true, 150, 167, ⟨1, 150⟩, .high⟩,
   ⟨1, true, 168, 87600, ⟨0, 318⟩, .high⟩,
   ⟨2, false, 0, 99, ⟨1, 200⟩, .normal⟩,
   ⟨2, false, 100, 167, ⟨1, 200⟩, .high⟩,
   ⟨2, false, 168, 87600, ⟨0, 368⟩, .high⟩,
   ⟨2, true, 0, 49, ⟨1, 250⟩, .normal⟩,
   ⟨2, true, 50, 167, ⟨1, 250⟩, .high⟩,
   ⟨2, true, 168, 87600, ⟨0, 418⟩, .high⟩,
   ⟨3, false, 0, 167, ⟨1, 300⟩, .high⟩,
   ⟨3, false, 168, 87600, ⟨0, 468⟩, .high⟩,
   ⟨3, true, 0, 149, ⟨1, 350⟩, .high⟩,
   ⟨3, true, 150, 167, ⟨1, 350⟩, .urgent⟩,
   ⟨3, true, 168, 87600, ⟨0, 518⟩, .urgent⟩,
   ⟨4, false, 0, 99, ⟨1, 400⟩, .high⟩,
   ⟨4, false, 100, 167, ⟨1, 400⟩, .urgent⟩,
   ⟨4, false, 168, 87600, ⟨0, 568⟩, .urgent⟩,
   ⟨4, true, 0, 49, ⟨1, 450⟩, .high⟩,
   ⟨4, true, 50, 167, ⟨1, 450⟩, .urgent⟩,
   ⟨4, true, 168, 87600, ⟨0, 618⟩, .urgent⟩,
   ⟨5, false, 0, 167, ⟨1, 500⟩, .urgent⟩,
   ⟨5, false, 168, 87600, ⟨0, 668⟩, .urgent⟩,
   ⟨5, true, 0, 167, ⟨1, 550⟩, .urgent⟩,
   ⟨5, true, 168, 87600, ⟨0, 718⟩, .urgent⟩]

theorem sampleCellCount : sampleCells.length = 26 := rfl
theorem sampleAccepted : checkTyped sampleProgram sampleCells = true := rfl
theorem alternateAccepted : checkTyped alternateProgram sampleCells = true := rfl
theorem sampleUnsortedAccepted :
    checkTyped sampleProgram sampleCells.reverse = true := rfl

theorem alternateProgramDifferent : sampleProgram ≠ alternateProgram := by
  intro h
  have hnodes := congrArg (fun p : Program => nodesI p.score) h
  change 10 = 16 at hnodes
  contradiction

/- Merge two age intervals across 168. Coverage stays complete, while the
   independent reference affine selection fails on the crossing interval. -/
def crossingReferenceCells : List Cell :=
  ⟨1, false, 0, 87600, ⟨0, 268⟩, .normal⟩ :: sampleCells.drop 2
theorem crossingReferenceCover : checkCover crossingReferenceCells = true := rfl
theorem crossingReferenceRejected :
    checkTyped sampleProgram crossingReferenceCells = false := rfl

def forgedScoreCells : List Cell :=
  ⟨1, false, 0, 167, ⟨1, 101⟩, .normal⟩ :: sampleCells.tail
theorem forgedScoreCover : checkCover forgedScoreCells = true := rfl
theorem forgedScoreRejected : checkTyped sampleProgram forgedScoreCells = false := rfl

def forgedPriorityCells : List Cell :=
  ⟨1, false, 0, 167, ⟨1, 100⟩, .high⟩ :: sampleCells.tail
theorem forgedPriorityRejected :
    checkTyped sampleProgram forgedPriorityCells = false := rfl

/- Age 149 gives 299 and age 150 gives 300 in this group. A merged interval
   covers the domain but cannot uniformly select the priority guard. -/
def nonuniformPriorityCells : List Cell :=
  sampleCells.take 2 ++ [⟨1, true, 0, 167, ⟨1, 150⟩, .normal⟩] ++ sampleCells.drop 4
theorem nonuniformPriorityCover : checkCover nonuniformPriorityCells = true := rfl
theorem nonuniformPriorityRejected :
    checkTyped sampleProgram nonuniformPriorityCells = false := rfl
theorem thresholdFalseCellAccepted :
    checkCell sampleProgram ⟨1, true, 149, 149, ⟨1, 150⟩, .normal⟩ = true := rfl
theorem thresholdTrueCellAccepted :
    checkCell sampleProgram ⟨1, true, 150, 150, ⟨1, 150⟩, .high⟩ = true := rfl
theorem urgentThresholdFalseCellAccepted :
    checkCell sampleProgram ⟨3, true, 149, 149, ⟨1, 350⟩, .high⟩ = true := rfl
theorem urgentThresholdTrueCellAccepted :
    checkCell sampleProgram ⟨3, true, 150, 150, ⟨1, 350⟩, .urgent⟩ = true := rfl

/- At age 168, the negative witness (-2,604), derived score (1,100),
   and independent reference (0,268) all have value 268. -/
def singletonWitnessCells : List Cell :=
  sampleCells.take 1 ++
    [⟨1, false, 168, 168, ⟨-2, 604⟩, .normal⟩,
     ⟨1, false, 169, 87600, ⟨0, 268⟩, .normal⟩] ++ sampleCells.drop 2
theorem singletonWitnessAccepted :
    checkTyped sampleProgram singletonWitnessCells = true := rfl
theorem singletonWitnessDifferent : (⟨-2, 604⟩ : Affine) ≠ ⟨0, 268⟩ := by decide
theorem singletonWitnessCellAccepted :
    checkCell sampleProgram ⟨1, false, 168, 168, ⟨-2, 604⟩, .normal⟩ = true := rfl

theorem emptyRejected : checkTyped sampleProgram [] = false := rfl
theorem missingGroupRejected :
    checkTyped sampleProgram (sampleCells.drop 2) = false := rfl

def gapCells : List Cell :=
  ⟨1, false, 0, 166, ⟨1, 100⟩, .normal⟩ :: sampleCells.tail
theorem gapCellsSemanticallyValid : gapCells.all (checkCell sampleProgram) = true := rfl
theorem gapRejected : checkTyped sampleProgram gapCells = false := rfl

def overlapCells : List Cell :=
  ⟨1, false, 167, 167, ⟨1, 100⟩, .normal⟩ :: sampleCells
theorem overlapCellsSemanticallyValid :
    overlapCells.all (checkCell sampleProgram) = true := rfl
theorem overlapRejected : checkTyped sampleProgram overlapCells = false := rfl

def duplicateCells : List Cell :=
  ⟨1, false, 0, 167, ⟨1, 100⟩, .normal⟩ :: sampleCells
theorem duplicateCellsSemanticallyValid :
    duplicateCells.all (checkCell sampleProgram) = true := rfl
theorem duplicateRejected : checkTyped sampleProgram duplicateCells = false := rfl

def invalidSeverityCells : List Cell :=
  ⟨6, false, 0, 167, ⟨1, 600⟩, .urgent⟩ :: sampleCells
theorem invalidSeverityCover : checkCover invalidSeverityCells = true := rfl
theorem invalidSeverityRejected :
    checkTyped sampleProgram invalidSeverityCells = false := rfl

/- Resource violations are rejected before the certificate phases. Existing
   boundary proofs in Syntax provide the exact 256/257 and 24/25 cutoffs. -/
theorem fullCheckerRejectsMalformed (p : Program) (cells : List Cell)
    (hwf : wfProgram p = false) : checkTyped p cells = false := by
  simp only [checkTyped, hwf, Bool.false_and]

private def fixtureZeroTerms : Nat → Terms false
  | 0 => .nil
  | n + 1 => .cons (.lit 0) (fixtureZeroTerms n)

private def fixtureWideProgram (tailLength : Nat) : Program :=
  ⟨.add (.lit 0) (.lit 0) (fixtureZeroTerms tailLength), .lit .normal⟩

set_option maxRecDepth 4096 in
theorem combinedNodesViolationRejected :
    checkTyped (fixtureWideProgram 253) sampleCells = false := by
  apply fullCheckerRejectsMalformed
  exact combined_nodes_257_reject

private def fixtureNestedMul : Nat → IExpr false
  | 0 => .lit 0
  | n + 1 => .mul 0 (fixtureNestedMul n)

theorem depth25ViolationRejected :
    checkTyped ⟨fixtureNestedMul 25, .lit .normal⟩ sampleCells = false := by
  apply fullCheckerRejectsMalformed
  exact root_depth_25_reject

theorem unselectedLiteralViolationRejected :
    checkTyped ⟨.ite .blocked (.lit 0) (.lit 1000001), .lit .normal⟩ sampleCells =
      false := fullCheckerRejectsMalformed _ _ unselected_branch_bounds_reject

theorem unselectedDepthViolationRejected :
    checkTyped ⟨.ite .blocked (.lit 0) (fixtureNestedMul 24), .lit .normal⟩ sampleCells =
      false := by
  apply fullCheckerRejectsMalformed
  rfl

theorem scalarMagnitudeViolationRejected :
    checkTyped ⟨.mul (-1000001) (.lit 0), .lit .normal⟩ sampleCells = false := by
  apply fullCheckerRejectsMalformed
  rfl

set_option maxRecDepth 4096 in
theorem tooManyCellsRejected :
    checkTyped sampleProgram
      (List.replicate 513 ⟨1, false, 0, 167, ⟨1, 100⟩, .normal⟩) = false := by
  simp only [checkTyped, List.length_replicate]
  rfl

end HermesTicket
