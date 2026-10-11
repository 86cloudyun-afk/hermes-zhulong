# Repository verification entry

This directory imports the independently reviewed typed ticket-checker proof.
The original 14 reviewed files, including `README.md` and `replay.py`, are
preserved byte for byte. `frozen-sources.json` is also unchanged. The original
README's scratch paths describe the research execution checkpoint; this page
describes the repository entry and CI packaging added afterward.

Run from any directory using Python 3.11 or newer. On Linux x86_64, the default
entry downloads the official pinned Lean distribution over verified HTTPS,
checks its exact size and SHA-256, validates archive paths/links, extracts only
into this package's ignored task-local cache, and verifies every recorded
compiler/library file before executing anything from that toolchain:

```sh
./formal/ticket-kernel/check.sh
```

Prerequisites for a fresh download are `curl`, `zstd` and GNU `tar`. The entry
preserves configured proxy/CA settings and never disables TLS verification or
changes the global toolchain. For an existing official pinned toolchain,
avoid a download and use explicit new output directories:

```sh
./formal/ticket-kernel/check.sh \
  --toolchain /absolute/path/to/lean-4.19.0 \
  --workdir /absolute/path/to/a/new/proof-replay \
  --evidence-dir /absolute/path/to/new/verification-logs
```

`--cache-dir` selects a task-local download/cache directory instead of
`--toolchain`. `HERMES_PROOF_PYTHON` selects the launcher executable when
needed; Python runs with `-I`, and the reviewed replay driver filters Lean,
Lake and loader override variables for compiler subprocesses. Existing
replay/evidence directories are rejected and preserved. Failed download,
extraction and replay files/logs are retained; the entry does not erase a bad
cache or silently replace a failed result.

The new verifier anchors the exact reviewed source-manifest SHA-256
`cd3fa704215fa48dec4215fa0ffd57b6ff4bf5994becddf06a21bdefd0b15f69`
and toolchain-tree SHA-256
`7c890479b405c695b835d0d7d81affad13c082975bde6ead33e608a57d9f12e2`
as literals before parsing them. Rewriting a manifest together with a proof
cannot authorize new bytes. It also requires the actual repository
`certified_ticket.py` to match
`232a90b524f8c248d764950bc021ab9fe2cc731c379fe5519b58bc99862fbbd2`
before and after replay. It independently derives all 83 public theorem names
from source and checks complete audit coverage, the exact foundational policy
and the no-axiom positive examples. A later checker/proof change requires new
reviewed identities rather than an arbitrary hash override.

Cached compiler objects are accepted only as part of the complete recorded
4617-entry official toolchain tree; extra, changed or special files fail.
Every local proof object is freshly built. With explicit `--toolchain`, the
historical install's nonruntime `provenance/` records are excluded from the
runtime tree, while a retained release archive is separately checked against
the exact archive size/SHA. Those excluded records are never searched for
imports. The CI cache contains the official extracted tree and the pinned
release archive in its parent directory. Every tree is reverified on a cache
hit; archive size/SHA and paths/links are checked before extraction on a miss.
No local proof objects are cached, and arbitrary `.olean` files cannot enter
the verified compiler/library tree.

Lean is fixed to 4.19.0, source commit
`6caaee842e9495688c1567e78c0e68dbb96942aa`; archive SHA-256 is
`6fe3ce97a58f44e2b3567d455b994eacec5bfe9ae7774f2a573444480ba813fe`
with exactly 343842845 bytes. Official release metadata supplies no publisher
digest. The trust is the official distribution over verified TLS followed by
local artifact pinning, not an independently authenticated publisher checksum.
The source compiler/bootstrap, bundled Lean foundations and host remain
trusted. No Mathlib, external package or model provider is used.

The dedicated [workflow](../../.github/workflows/formal.yml) uses Ubuntu 24.04,
explicit Python 3.11, the exact toolchain cache key, a fresh replay directory,
and a separate artifact containing command exits, complete outputs, hashes,
download/archive provenance when applicable, and all theorem closures. The
existing Python workflow remains independent. Local verification does not
constitute a GitHub Actions execution result.

The verifier's boundary checks can also be run separately:

```sh
HERMES_TEST_LEAN_TOOLCHAIN=/absolute/path/to/lean-4.19.0 \
  python3 -I formal/ticket-kernel/test_verify.py
```

Without that variable only the full real-toolchain positive replay is skipped;
the failure-boundary checks still execute. The main `check.sh` always requires
the complete actual proof replay.

The scope remains the [typed proof](README.md). A matching Python source hash
and a successful build do not prove the JSON/Python representation bridge,
runtime interpreter, ticket-list sorting/output, native admission/session/IO,
subjective consciousness or benefit. The deployed Python checker continues to
report `reviewed_argument_not_machine_formalized`. Original execution and
independent review records are under `evidence/`; those records are historical
results, and each new invocation writes its own actual outputs separately.
