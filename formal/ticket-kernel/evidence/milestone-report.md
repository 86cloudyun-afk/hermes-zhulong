# Private formal milestone execution report

Status: **kernel build, dependency audit and frozen-source clean replay PASS**.
Independent final source review and repository integration remain pending.
No repository, runtime, provider, paid batch, Docker or global tool mutation
was performed by this proof task.

## Result actually checked

`HermesTicket.rowCertificateSound` proves, for every modeled program, typed
certificate and legal row:

```text
checkTyped program cells = true -> validRow row ->
  evalScore program row = specScore row /\
  evalRowPriority program row = businessPriority (specScore row)
```

The premise is the computed full checker. It includes the combined program
node budget, all-branch scalar/literal and root-depth limits, certificate
length, all-cell validation, the exact ten-group sorted contiguous cover,
and every cell's successful derivation, reference/witness equality and
independent priority checks. The theorem does not assume these semantic facts.
`accepted_coverage_unique` additionally establishes uniqueness of the original
certificate occurrence index; `accepted_resources` extracts computed limits.
The evaluator/deriver definitions are structurally terminating for the full
typed grammar; this is not an arbitrary-program correctness decider.

Full proofs cover affine sign cases, n-ary addition with every operand at the
same source-child depth, conditional/Boolean guard uniformity, ordered min
ties, cached-score priority context, and endpoint value equality including
singletons with unequal affine coefficient pairs. Coverage is proved by chain
induction and transferred through the filtered sort's occurrence-preserving
permutation. There is no numeric row enumeration in the proof.

## Nonvacuity and edge evidence

`sampleAccepted`, `alternateAccepted` and `sampleUnsortedAccepted` are ordinary
kernel-reduction proofs with **no axiom dependencies**. The alternate AST is
proved different and includes negative intermediate coefficients, cancelling
age operands and an extra n-ary operand. Its acceptance therefore tests more
than the reference formula alone. The 26 cells match the supplied pure public
bundle in order and value; `evidence/fixture-origin-comparison.json` records
the program/certificate header and data equality, without asserting a parser
refinement theorem.

Additional checked proofs reject complete-cover reference-boundary crossings,
score/priority forgeries, nonuniform priority guards, gaps, overlaps, repeated
occurrences, empty/missing groups, invalid extra severity, more than 512 cells,
257 combined AST nodes, root depth 25, invalid scalar/literal magnitudes and
unselected invalid branches. Boundary proofs accept exactly 256 nodes and
root depth 24, both priority thresholds, negative-slope cells and a singleton
at age 168 with negative supplied slope. All 83 public theorem closures were
audited in the clean replay.

## Actual execution and immutable bytes

- Lean: `Lean (version 4.19.0, x86_64-unknown-linux-gnu, commit 6caaee842e94, Release)`.
- Lake: `Lake version 5.0.0-6caaee8 (Lean version 4.19.0)`.
- Official source commit: `6caaee842e9495688c1567e78c0e68dbb96942aa`.
- Official archive: 343842845 bytes, local SHA-256
  `6fe3ce97a58f44e2b3567d455b994eacec5bfe9ae7774f2a573444480ba813fe`.
- Publisher digest: **null**. Official verified-TLS distribution and local
  artifact consistency are the stated trust; no independent publisher
  checksum authentication is claimed.
- Frozen 14-file source/configuration manifest SHA-256:
  `cd3fa704215fa48dec4215fa0ffd57b6ff4bf5994becddf06a21bdefd0b15f69`.
- Extracted toolchain tree: 4617 file/symlink entries, 1672908404 file bytes;
  manifest SHA-256
  `7c890479b405c695b835d0d7d81affad13c082975bde6ead33e608a57d9f12e2`.
- Clean replay result SHA-256:
  `2eec2f047cf31cc792c85f4fdb8b2b8704db852034489761d0b642781aa386e4`.

Clean replay command (outer process also returned exit 0):

```sh
python3 /workspace/scratch/hermes-core-v11/formal-proof-v1/replay.py \
  --toolchain /workspace/scratch/hermes-core-v11/formal-proof-v1/toolchain \
  --workdir /workspace/scratch/hermes-core-v11/formal-proof-replay-1
```

The replay copied only frozen source/configuration to a directory that did not
exist, reused no local proof `.olean`, and retained separate command output
and exits for Lean version, Lake version, `lake build HermesTicket`, and the
kernel audit. All four exited **0**. Full logs and result are under
`/workspace/scratch/hermes-core-v11/formal-proof-replay-1/replay-evidence/`.
Source and complete extracted toolchain bytes matched both before and after.

The general theorem depends exactly on `propext`, `Quot.sound` and
`Classical.choice`; the per-cell theorem uses `propext` and `Quot.sound`.
Among 83 public theorem closures, 51 use no axioms, 11 use `propext`, 14 use
`propext` plus `Quot.sound`, and 7 use all three declared foundations. No
`sorryAx`, user axiom, native evaluator or oracle dependency appeared. The
official compiler/bootstrap and bundled foundational libraries are trusted;
the foundation allowlist does not prove those binary distributions themselves.

## Honest applicability boundary

The model source mapping targets `certified_ticket.py` SHA-256
`232a90b524f8c248d764950bc021ab9fe2cc731c379fe5519b58bc99862fbbd2`,
confirmed unchanged during this task. Source inspection is not a verified
Python-to-Lean refinement. JSON/UTF-8/type/header/byte-limit decoding, tuple
conversion, Python integer/Unicode and exception behavior, same-AST execution
bridge, input data canonicalization, list insertion sort/output/ID semantics,
hash/session/admission/SQLite/filesystem IO, compiler/host integrity and real
wall-clock completion remain outside the theorem. The Lean cell sort proves
coverage permutation; it does not prove the Python ticket-output insertion
sort's append/shift algorithm.

This milestone provides an actual machine-checked theorem for a restricted
typed checker model. It does not establish deployed Python checker soundness,
subjective consciousness, universal correctness or long-term benefit. The
runtime's `reviewed_argument_not_machine_formalized` status remains appropriate
until the missing bridge is separately mechanized and reviewed. Earlier
UNRUN research checkpoints remain historically accurate.
