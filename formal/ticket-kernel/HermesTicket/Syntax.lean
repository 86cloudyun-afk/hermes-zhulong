import HermesTicket.Interfaces

namespace HermesTicket

/- The context index permits a cached score reference only in priority guards.
   The first two operands of add are explicit; Terms is representation only. -/
mutual
  inductive IExpr (ctx : Bool) where
    | lit (n : Int)
    | severity
    | age
    | score (allowed : ctx = true)
    | add (first second : IExpr ctx) (rest : Terms ctx)
    | mul (scalar : Int) (arg : IExpr ctx)
    | min (left right : IExpr ctx)
    | ite (guard : BExpr ctx) (yes no : IExpr ctx)
  inductive BExpr (ctx : Bool) where
    | blocked
    | ge (left right : IExpr ctx)
  inductive Terms (ctx : Bool) where
    | nil
    | cons (head : IExpr ctx) (tail : Terms ctx)
end

inductive PExpr where
  | lit (priority : Priority)
  | ite (guard : BExpr true) (yes no : PExpr)

structure Program where
  score : IExpr false
  priority : PExpr

structure Env where
  severity : Int
  age : Int
  blocked : Bool
  score : Int

mutual
  def evalI : IExpr ctx → Env → Int
    | .lit n, _ => n
    | .severity, env => env.severity
    | .age, env => env.age
    | .score _, env => env.score
    | .add first second rest, env =>
        evalI first env + evalI second env + evalTerms rest env
    | .mul scalar arg, env => scalar * evalI arg env
    | .min left right, env => min (evalI left env) (evalI right env)
    | .ite guard yes no, env =>
        if evalB guard env then evalI yes env else evalI no env
  def evalB : BExpr ctx → Env → Bool
    | .blocked, env => env.blocked
    | .ge left right, env => decide (evalI left env ≥ evalI right env)
  def evalTerms : Terms ctx → Env → Int
    | .nil, _ => 0
    | .cons head tail, env => evalI head env + evalTerms tail env
end

def evalP : PExpr → Env → Priority
  | .lit priority, _ => priority
  | .ite guard yes no, env => if evalB guard env then evalP yes env else evalP no env

def evalScore (p : Program) (r : Row) : Int :=
  evalI p.score ⟨r.severity, r.age, r.blocked, 0⟩

def evalRowPriority (p : Program) (r : Row) : Priority :=
  evalP p.priority ⟨r.severity, r.age, r.blocked, evalScore p r⟩

def Terms.operands : Terms ctx → List (IExpr ctx)
  | .nil => []
  | .cons head tail => head :: tail.operands

theorem evalTerms_eq_operand_sum (terms : Terms ctx) (env : Env) :
    evalTerms terms env = (terms.operands.map (fun e => evalI e env)).sum := by
  cases terms with
  | nil => rfl
  | cons head tail => simp [evalTerms, Terms.operands, evalTerms_eq_operand_sum tail env]
termination_by structural terms

/- Source node counts deliberately exclude the Terms chain. Scalar integers are
   opcode parameters, not literal expression nodes. Both if branches count. -/
mutual
  def nodesI : IExpr ctx → Nat
    | .lit _ | .severity | .age | .score _ => 1
    | .add first second rest => 1 + nodesI first + nodesI second + nodesTerms rest
    | .mul _ arg => 1 + nodesI arg
    | .min left right => 1 + nodesI left + nodesI right
    | .ite guard yes no => 1 + nodesB guard + nodesI yes + nodesI no
  def nodesB : BExpr ctx → Nat
    | .blocked => 1
    | .ge left right => 1 + nodesI left + nodesI right
  def nodesTerms : Terms ctx → Nat
    | .nil => 0
    | .cons head tail => nodesI head + nodesTerms tail
end

def nodesP : PExpr → Nat
  | .lit _ => 1
  | .ite guard yes no => 1 + nodesB guard + nodesP yes + nodesP no

/- Python AST root depth is zero. Each add operand has the same parent+1
   depth, however far along the representation tail it occurs. -/
mutual
  def limitsI : IExpr ctx → Nat → Bool
    | .lit n, depth => decide (depth ≤ 24) && boundedInt n
    | .severity, depth | .age, depth | .score _, depth => decide (depth ≤ 24)
    | .add first second rest, depth =>
        decide (depth ≤ 24) && limitsI first (depth + 1) &&
        limitsI second (depth + 1) && limitsTerms rest (depth + 1)
    | .mul scalar arg, depth =>
        decide (depth ≤ 24) && boundedInt scalar && limitsI arg (depth + 1)
    | .min left right, depth =>
        decide (depth ≤ 24) && limitsI left (depth + 1) && limitsI right (depth + 1)
    | .ite guard yes no, depth =>
        decide (depth ≤ 24) && limitsB guard (depth + 1) &&
        limitsI yes (depth + 1) && limitsI no (depth + 1)
  def limitsB : BExpr ctx → Nat → Bool
    | .blocked, depth => decide (depth ≤ 24)
    | .ge left right, depth =>
        decide (depth ≤ 24) && limitsI left (depth + 1) && limitsI right (depth + 1)
  def limitsTerms : Terms ctx → Nat → Bool
    | .nil, _ => true
    | .cons head tail, depth => limitsI head depth && limitsTerms tail depth
end

def limitsP : PExpr → Nat → Bool
  | .lit _, depth => decide (depth ≤ 24)
  | .ite guard yes no, depth =>
      decide (depth ≤ 24) && limitsB guard (depth + 1) &&
      limitsP yes (depth + 1) && limitsP no (depth + 1)

def wfProgram (p : Program) : Bool :=
  decide (nodesI p.score + nodesP p.priority ≤ 256) &&
  limitsI p.score 0 && limitsP p.priority 0

/- These defining lemmas make resource mapping inspectable independently of
   fixtures: tail positions do not increase source depth or node count. -/
theorem nodesTerms_cons (head : IExpr ctx) (tail : Terms ctx) :
    nodesTerms (.cons head tail) = nodesI head + nodesTerms tail := rfl

theorem limitsTerms_cons (head : IExpr ctx) (tail : Terms ctx) (depth : Nat) :
    limitsTerms (.cons head tail) depth = (limitsI head depth && limitsTerms tail depth) := rfl

theorem literal_depth_24 : limitsI (IExpr.lit (ctx := false) 0) 24 = true := rfl
theorem literal_depth_25 : limitsI (IExpr.lit (ctx := false) 0) 25 = false := rfl
theorem scalar_lower_bound : limitsI (IExpr.mul (ctx := false) (-1000000) (.lit 0)) 0 = true := rfl
theorem scalar_below_bound : limitsI (IExpr.mul (ctx := false) (-1000001) (.lit 0)) 0 = false := rfl

private def zeroTerms : Nat → Terms false
  | 0 => .nil
  | n + 1 => .cons (.lit 0) (zeroTerms n)

private def wideProgram (tailLength : Nat) : Program :=
  ⟨.add (.lit 0) (.lit 0) (zeroTerms tailLength), .lit .normal⟩

set_option maxRecDepth 4096 in
theorem combined_nodes_256_accept : wfProgram (wideProgram 252) = true := rfl
set_option maxRecDepth 4096 in
theorem combined_nodes_257_reject : wfProgram (wideProgram 253) = false := rfl

private def nestedMul : Nat → IExpr false
  | 0 => .lit 0
  | n + 1 => .mul 0 (nestedMul n)

theorem root_depth_24_accept :
    wfProgram ⟨nestedMul 24, .lit .normal⟩ = true := rfl
theorem root_depth_25_reject :
    wfProgram ⟨nestedMul 25, .lit .normal⟩ = false := rfl

theorem unselected_branch_bounds_reject :
    wfProgram ⟨.ite .blocked (.lit 0) (.lit 1000001), .lit .normal⟩ = false := rfl

end HermesTicket
