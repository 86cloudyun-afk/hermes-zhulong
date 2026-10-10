# Zhulong v0.5 supervised runtime

Date: 2026-10-10. Continues the user's authorized research, engineering,
testing, independent review, PR and merge workflow after v0.4 (`1be55a1`).
This specification is the engineering interpretation of “继续开发后续工程”,
not a claim of newly received artifact approval or subjective consciousness.

## Result and scope

Provide a foreground, stdlib Linux supervisor for one native Hermes gateway.
Reuse the plugin's Controller and `ctx.llm`; no second cognitive scheduler.
Deliver a retained profile, startup/stop/health protocol, persistent bounded
restart allowance, Docker worker policy and executable deployment checks.
Include a Linux systemd example for an actual persistent host. The Codex cloud
task has no systemd PID 1; its snapshots do not preserve processes.

The trusted control plane comprises native Hermes, this plugin, the supervisor,
protected profile/configuration, verification and Docker daemon. The model's
execution plane has only native terminal/process tools inside a Docker worker.
This is an OS boundary for model-issued actions, not a jail for malicious trusted
plugins, the Docker daemon or another host process with the same user privileges.

## Protected execution policy

1. Dedicated profile outside every authorized workspace; workspace must also
   exclude plugin/native host code. Configuration is valid JSON (also YAML),
   immutable for a running supervisor and hashed without credentials.
2. Pin the native host revision and worker image digest. Load only Zhulong as
   a user plugin (native bundled provider/platform plugins remain trusted),
   default context engine, no MCP, API surface `[terminal, no_mcp]`, and known
   plugin toolsets `[zhulong]`. Check the final concrete schemas, not only the
   `/v1/toolsets` endpoint. Unexpected tool names block startup.
3. Use the native Docker backend, nonroot host UID, read-only root, network none,
   no host cwd mount, no environment forwarding or credential mounts,
   no cross-process reuse, no persistent container home. Native automatically
   mounts cache directories; allow only read-only named caches in this dedicated
   profile and an empty skills directory. They contain this runtime's data.
   Bind only
   authorized work at identical absolute paths; source facts get read-only
   overlays. Never mount profile controls, plugin code or the Docker socket.
4. Enforce CPU, memory, PID and tmpfs limits in actual Docker configuration.
   Inspect mounts/user/network/security/resource settings and execute denied
   control-file/socket/network checks before permitting new work. Docker vfs
   cannot enforce a bind-volume disk quota; report that limit explicitly.
5. Secure profile contracts accept only data checks (`file_contains`,
   `json_equals`, `file_exists` if supported by the core). Reject host `argv`
   verification of model-authored code. Existing v0.4 behavior outside this
   dedicated runtime remains compatible.
6. Local API listens on loopback with a separately generated private strong
   key. DeepSeek defaults to `deepseek-flash`; provider credentials stay in
   the injected vault environment and are never written to reports or workers.

## Supervision and plugin lifecycle

The supervisor holds a POSIX flock and passes it to the gateway child. An
orphan gateway therefore blocks a duplicate launch after supervisor death.
One persisted launch budget survives supervisor restarts; exhaustion blocks
with a reason. Restart never refunds workload budgets or changes submission
IDs, frozen intent, execution namespace or unresolved occupancy.

Each gateway boot receives a fresh boot ID. A private atomic control record
starts at `starting`; only matching `running` allows new planning/dispatch.
Recovery may continue while starting or stopping. Health contains matching
boot/PID, controller progress, tick/error counts and sanitized reason codes.
Require authenticated readiness JSON, native durable run capabilities and
fresh plugin health before moving to running. A responding `/health` alone
is insufficient. Watch progress, not merely a heartbeat thread.

Stopping closes admission before gateway draining. Publish `stopping`, wait
for matching acknowledgement, signal the owned process group, escalate through
a bounded deadline and clean only containers labelled with this deployment.
Do not mark uncertain executions settled to obtain a clean exit. Gateway exit
does not imply plugin unload; explicit control and thread joining are required.
Outer process-manager cgroup cleanup is required for supervisor/host failure;
the lock alone deliberately prevents duplicates but cannot reap an orphan.

## Durable recovery refinements

Planning leases count completed plans, not crash-only claims. Auxiliary model
budget remains charged before calls, so repeated uncertain calls are bounded.
Migrate expired legacy planning reservations without erasing completed failures.
Final verified outcome must remain consistent with its immutable evidence when
tracking becomes unavailable; execution uncertainty remains separately visible
and retains occupancy until quiescence is established.

## Acceptance evidence

- Full existing/native offline suite remains green.
- New tests reproduce crash-only source exhaustion and verified-truth downgrade
  before fixes; stop gates prevent new planner/admission calls and preserve
  recovery; health cannot report running for stale/wrong boot records.
- Fresh-process fixture campaign independently counts endpoint admissions,
  effects and restarts. Lost replies/crashes retain one immutable submission;
  bounded restart, duplicate lock, shutdown and stale health are measured.
- Real pinned native Docker checks validate snapshot initialization, nonroot
  UID, effective capabilities, read-only controls/facts, absent secrets/socket,
  disabled networking and actual resource settings. Failures block startup.
- Start and stop the real native gateway under the supervisor; provider-free
  readiness does not claim provider connectivity. A bounded real DeepSeek goal
  may supply separate execution evidence if available within configured limits.
- Fresh whole-branch independent review, fixes with reproducing tests, CI and PR
  merge. Reports distinguish finite fault tests from long-term availability.

## Deferred work

No real mail/calendar accounts, unbounded external browsing, automatic kernel
promotion, automatic unknown-execution settlement, paid infinite daemon trial,
24-hour soak, container bind-volume disk quota or subjective consciousness claim.
