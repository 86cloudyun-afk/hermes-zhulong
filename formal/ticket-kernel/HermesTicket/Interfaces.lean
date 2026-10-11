import Std

namespace HermesTicket

/- Fixed typed-model identity. Byte/header decoding and Python correspondence
   remain outside this model. No certificate may change these constants. -/
def modelVersion : Nat := 1
def referenceId : String := "ticket_priority_v1"

inductive Priority where
  | urgent | high | normal
  deriving DecidableEq, Repr

structure Affine where
  slope : Int
  intercept : Int
  deriving DecidableEq, Repr

def Affine.value (f : Affine) (age : Int) : Int := f.slope * age + f.intercept
def Affine.add (f g : Affine) : Affine := ⟨f.slope + g.slope, f.intercept + g.intercept⟩
def Affine.scale (k : Int) (f : Affine) : Affine := ⟨k * f.slope, k * f.intercept⟩
def Affine.sub (f g : Affine) : Affine := ⟨f.slope - g.slope, f.intercept - g.intercept⟩
def Affine.zero : Affine := ⟨0, 0⟩
def extrema (f : Affine) (lo hi : Int) : Int × Int :=
  (min (f.value lo) (f.value hi), max (f.value lo) (f.value hi))
def equalOnCell (f g : Affine) (lo hi : Int) : Bool :=
  extrema (f.sub g) lo hi == (0, 0)

structure Row where
  severity : Int
  age : Int
  blocked : Bool
  deriving DecidableEq, Repr

def validRow (r : Row) : Prop :=
  1 ≤ r.severity ∧ r.severity ≤ 5 ∧ 0 ≤ r.age ∧ r.age ≤ 87600

structure Cell where
  severity : Int
  blocked : Bool
  lo : Int
  hi : Int
  witness : Affine
  priority : Priority
  deriving DecidableEq, Repr

def Cell.contains (c : Cell) (r : Row) : Prop :=
  c.severity = r.severity ∧ c.blocked = r.blocked ∧ c.lo ≤ r.age ∧ r.age ≤ c.hi

def boundedInt (n : Int) : Bool := decide (-1000000 ≤ n ∧ n ≤ 1000000)
def validCell (c : Cell) : Bool :=
  decide (1 ≤ c.severity ∧ c.severity ≤ 5 ∧ 0 ≤ c.lo ∧ c.lo ≤ c.hi ∧ c.hi ≤ 87600) &&
  boundedInt c.witness.slope && boundedInt c.witness.intercept

def baseScore (severity : Int) (blocked : Bool) : Int :=
  100 * severity + (if blocked then 50 else 0)
def specScore (r : Row) : Int := baseScore r.severity r.blocked + min r.age 168
def businessPriority (score : Int) : Priority :=
  if score ≥ 500 then .urgent else if score ≥ 300 then .high else .normal

def referenceAffine (c : Cell) : Option Affine :=
  if c.hi < 168 then some ⟨1, baseScore c.severity c.blocked⟩
  else if c.lo ≥ 168 then some ⟨0, baseScore c.severity c.blocked + 168⟩
  else none

def priorityRelation (p : Priority) (f : Affine) (lo hi : Int) : Bool :=
  let bounds := extrema f lo hi
  match p with
  | .urgent => decide (bounds.1 ≥ 500)
  | .high => decide (bounds.1 ≥ 300 ∧ bounds.2 < 500)
  | .normal => decide (bounds.2 < 300)

end HermesTicket
