# Autonomous Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可主动发现目标、通过 Hermes 执行、独立验收、更新自我模型和故障恢复的 v0.4 自主核心，并修复现有并发认领与预算。

**Architecture:** 保留 Hermes 工具循环和烛龙元数据观测。新增事务账本、配置化机械验收、公开 Runs 适配及证据型自我模型；控制层在有限 tick 中合成、派发、核验和恢复。所有模型 / 网络 / 长检查在 SQLite 写事务之外。

**Tech Stack:** Python 标准库、sqlite3、unittest、urllib.request、subprocess；固定 Hermes 官方 PM 环境。

**Spec:** [已批准规格](../specs/2026-10-09-autonomous-core-design.md)。执行分支：`feat/zhulong-autonomy-core`；现有云任务已隔离，不另建 worktree。

## Global Constraints

- 保留 11 个观测 hooks 的元数据与 fail-open 行为。
- 产品继续只用 Python 标准库；不新增远程数据库或模型 SDK 依赖。
- 固定宿主基线为 `73162b00eefde3794bed0afb53d84a19c0eed230`。
- 模型辅助调用通过 `ctx.llm`，沿用用户选择的 `deepseek / deepseek-flash`；不保存或覆盖凭据。
- 旧 `zhulong.db`、JSONL、校准账和既有命令继续可读；新工作流使用 `$HERMES_HOME/zhulong/autonomy.db`。
- `autonomy.enabled=false` 默认不派发；`ZHULONG_NO_AUTOSWEEP=1` 仍关闭自动后台运行。
- 默认 `daily_runs=8`、`max_active=1`、`max_candidates=3`、`lease_seconds=120`、`run_deadline_seconds=600`、`max_attempts=3`、`request_timeout_seconds=15`。
- 时间、并发、候选数和尝试数为正整数；每日运行次数允许零，表示停用；布尔值不作为整数。
- 来源读取及检查输出上限 64 KiB；argv 检查默认超时 15 秒。目标 / 理由各最多 500 个字符；新目标置信度为有限 `0..1` 或 `None`。
- 每日辅助调用默认 40，和 S4 / 探针共享原子计数；`cap=0` 不允许调用。
- 只有准备新的独立 submission 才增加尝试 / 派发预算；恢复、重放、查询、核验在耗尽新派发预算或暂停后继续。
- `interrupted` 不证明执行静止；不确定在途工作保留占额。请求、会话 affinity、执行身份版本在 submission 内冻结。
- 新数据只存自主任务意图、授权派生摘要和证据；不采集工具正文、原始聊天或私有推理。
- 本版报告实际通过的窄能力，不报告主观意识、未验证长期稳定性或严格全局费用封顶。

## Review Focus

1. 最后一次尝试 / 预算耗尽后崩溃：仍能恢复同一次提交，无新增尝试或重复动作（Task 2、4、6）。
2. 认证命名空间或 session affinity 改变：未决请求不能变成新接纳（Task 4、6）。
3. `interrupted` 后迟到副作用：当前无产物不能授权替代执行，保留不确定占额（Task 4、6）。
4. 验证进程挂起 / 大量输出 / 符号链接越界：有有限资源和正确未知结果（Task 3）。
5. 原有产物、重复回执、重试后的成功：不冒领新成果；目标预测只结算一次，首次与累计成功分开（Task 2、5、6）。

---

## Task 1: S4 原子预算与有所有权的认领

**Files:** Modify `reflect.py`, `probes.py`, `tests/test_reflect.py`; Create `tests/test_durable_reflect.py`.

**Interfaces:**
- 保留 `Db(path)`、`Tasks(db, max_attempts=5)`、`claim(task)->bool`、`unclaim(task)`、`Budget(db, cap=40).take()->bool`。
- 新增 `TaskLease(task:str, owner:str, generation:int, expires_at:float)`、`Tasks.acquire(task)->TaskLease|None`、`renew(lease)->bool`、`complete(lease)->bool`、`fail(lease)->bool`。
- 新增 `Tasks.heartbeat(lease)` 与短写入 `Tasks.fence(lease)` 上下文；S4 默认租约 900 秒、心跳 30 秒。`Reflector.run(..., lease=None)` 与 `Probes.run(lease=None)` 允许调度携带所有权。
- `Db.close()` 显式释放连接；旧任务迁移保守标记，不重放既有非空认领。

- [ ] **Step 1: 写失败测试。** `test_atomic_cap_across_connections` 用独立连接 / 进程同起，cap=1 最多一次允许且最终计数 1；`test_cap_zero_stops_calls`：

```python
assert Budget(db, cap=0).take() is False
assert Budget(db, cap=0).used_today() == (0, 0)
```

另测重试行只认领一次、到期接管后旧 lease 的 renew / complete / fail 全为 false、旧数据迁移、重复无效释放不增加失败次数。原重试测试改为每次合法 claim 后 fail，保持同一最大失败次数验收。
- [ ] **Step 2: 运行 `python3 -m unittest discover -s tests -p 'test_*reflect.py' -v`，确认新预算 / 租约行为失败。**
- [ ] **Step 3: 实现 schema 迁移、条件更新与原子计数。** cap 比较与递增同一写操作并检查影响行数；claim / 更新在短事务中校验 owner、generation 和当前租约；正常完成与可重试失败分开。调度在模型调用外续租，本地反思 / 探针落盘通过短 fence，观察日志写入在事务提交后进行。
- [ ] **Step 4: 运行上述测试及完整旧 suite，确认合法重试、校准、digest、探针仍通过。**
- [ ] **Step 5: 提交 `fix: make reflection claims and budgets atomic`。**

## Task 2: 自主事务账本与恢复计数

**Files:** Create `autonomy_store.py`, `tests/test_autonomy_store.py`, `tests/helpers.py`.

**Interfaces:**
- `GoalLease(goal_id:str, owner:str, generation:int, expires_at:float)`。
- `Ledger(path:Path, timeout_seconds:float=5.0)`：每操作短连接，显式事务 / rollback，`foreign_keys=ON`、`synchronous=FULL`；新数据库采用默认 DELETE journal，不改现有 journal 的模式。
- `create_goal(candidate:dict, source_revision:str, contract:dict, baseline:dict, now:float, deadline_seconds:int)->dict`；按 source / revision / contract 去重。
- `claim(owner:str, now:float, lease_seconds:int, ranked_goal_ids:tuple[str,...]=())->GoalLease|None`、`renew(lease, now, lease_seconds)->bool`。
- `prepare_submission(lease, request:dict, session_key:str, execution_identity:dict, now:float, daily_cap:int, max_active:int, max_attempts:int, retention_seconds:int)->dict` 返回 admitted / reason / submission。
- `record_admission(lease, submission_id:str, run_id:str, host_status:str, now:float)->bool`。
- `transition(lease, state:str, reason:str, now:float, execution_settled:bool|None=None)->bool` 与 `record_attempt_result(lease, submission_id:str, evidence:dict, now:float)->bool`：条件更新；允许明确安全的重试回到 ready，保留每次尝试证据，不提前结算目标级预测。
- `finish(lease, evidence:dict, outcome:str, execution_settled:bool, now:float)->bool`；事务校验验收 hash、插入证据及终态，重复 receipt 幂等。
- `get_goal(id)->dict|None`、`goals(limit=20)->list[dict]`、`submission(id)->dict|None`、`source_state(id)->dict|None`、`mark_source(id, fingerprint, outcome, now)->None`、`set_pause(bool)->None`、`paused()->bool`、`model_records()->dict`、`save_model(snapshot:dict)->dict`、`model_versions(limit=20)->list[dict]`。
- `tests.helpers.make_goal(ledger, now=1000.0, domain='code', source_revision='r1')->dict` 只创建独立、已配置验收的测试目标，不执行外部动作。

- [ ] **Step 1: 写失败测试。** goal 版本去重，进程竞争认领 / cap=1 派发，最后一次 prepare 后恢复、旧 owner 更新拒绝、事务失败不接纳、未知占额、一次 outcome receipt。恢复断言：

```python
assert reopened.get_goal(goal_id)['attempts'] == 1
assert reopened.record_admission(old_lease, submission_id, 'run_old', 'running', 1002.0) is False
assert reopened.get_goal(goal_id)['attempts'] == 1
```

加入子进程 prepare 后 `os._exit`，重新打开同一数据库，确认原提交 / 预算保留，恢复不需新的 admission allowance。
- [ ] **Step 2: 运行 `python3 -m unittest discover -s tests -p 'test_autonomy_store.py' -v`，确认缺少模块 / 行为导致失败。**
- [ ] **Step 3: 实现 goals、submissions、sources、evidence、run_budget、settings、model_versions。** 稳定业务 operation 与尝试 submission 分开；请求 / session key / 执行身份冻结；认领先处理已有提交且不受新派发预算限制；未知 execution 不释放 active accounting。
- [ ] **Step 4: 重跑上述测试，包含真实子进程崩溃及多进程竞争。**
- [ ] **Step 5: 提交 `feat: add durable autonomous goal ledger`。**

## Task 3: 配置、来源与机械验收

**Files:** Create `autonomy_checks.py`, `tests/test_autonomy_checks.py`.

**Interfaces:**
- `validate_config(raw:dict, base:Path)->dict` 返回规范化 policy；sources 含 id/domain/path、可选 JSON `input_fields`、命名 contracts，身份版本必填；所有秘密仅以 env 名引用。
- `observe_sources(policy:dict)->list[dict]` 输出 id/domain/revision/临时事实摘要 / 可用 contract ID；相关内容指纹忽略 mtime，可选字段筛选不奖励无关随机字段。
- `validate_candidates(raw:object, observations:list[dict], policy:dict)->list[dict]` 仅接受 source_id / contract_id / objective / reason / expected_benefit / confidence；expected_benefit 为有限 `0..1`，缺省 0.5；confidence 可弃答。拒绝额外权限字段、未知来源、NaN / Infinity / 布尔数值及超长文本。
- `Verifier(policy:dict).capture(contract:dict)->dict`、`.check(contract:dict, baseline:dict)->dict` 输出 verdict（true / false / unknown / already_satisfied）、contract_hash、artifact_hash、bounded reason。
- contracts：`file_contains(path,text)`、`json_equals(path,field,value)`、`argv(argv,cwd)`；require_change / safe_retry 为配置布尔值，default false；argv 显式可信、`shell=False`。

- [ ] **Step 1: 写失败测试。** 可信配置缺字段 / 布尔限额 / 非有限 confidence、路径 `..`、符号链接逃逸、坏 JSON、源 64 KiB 超限、未知 contract、原产物冒领、新 hash 合格；进程挂起和大量输出：

```python
assert hanging_result['verdict'] == 'unknown'
assert excessive_output_result['verdict'] == 'unknown'
assert prior_artifact_result['verdict'] == 'already_satisfied'
```

确认被启动的检查进程已退出；stdout 私密标记不进入 evidence，source 中夹带改验收指令不改变 policy。
- [ ] **Step 2: 运行 `python3 -m unittest discover -s tests -p 'test_autonomy_checks.py' -v`，确认失败。**
- [ ] **Step 3: 实现严格解析、授权根解析及有界读取。** 新产物比较 baseline；argv 使用有界流读取、15 秒 deadline 与进程清理，不先 capture 无限输出；不在 SQLite 事务内执行检查。
- [ ] **Step 4: 重跑测试，确认限额、清理和状态语义。**
- [ ] **Step 5: 提交 `feat: add bounded autonomous verification contracts`。**

## Task 4: 公开 Runs API 适配

**Files:** Create `hermes_runs.py`, `tests/test_hermes_runs.py`.

**Interfaces:**
- `RunsClient(api_url:str, credential_env:str, identity_version:str, timeout_seconds:int=15)`；读取 env 时不持久化或暴露值。
- `capabilities()->dict` 要求公开 run 提交 / 状态 / stop 及持久幂等，返回 retention_seconds。
- `submit(submission:dict)->dict`、`status(submission:dict)->dict`、`stop(submission:dict)->dict`。
- `RunsError(code:str, retryable:bool=False, admission_unknown:bool=False)` 不携带原始响应正文 / auth。
- canonical request 与 session affinity 来自已冻结 submission；HTTP 使用 env proxy / CA，环回 HTTP 或远端 HTTPS，响应读取有上限。

- [ ] **Step 1: 写失败测试。** stdlib HTTP 服务器保留同键后主动断开连接，重试仍只有一条 run；改 payload / session key 冲突，身份版本变化不提交；durable=false / 401 / 缺 env / 超大响应正确受阻；interrupted 只返回事实：

```python
assert service.admissions == 1
assert second['run_id'] == first['run_id']
assert interrupted['status'] == 'interrupted'
assert service.replacement_admissions == 0
```

额外用固定宿主真实持久幂等存储测试 reservation、死 owner hydration 与终态重放；该测试属于宿主集成，不被伪称 HTTP 模型执行。
- [ ] **Step 2: 运行 `python3 -m unittest discover -s tests -p 'test_hermes_runs.py' -v`，确认失败。**
- [ ] **Step 3: 实现 urllib 公开请求、可诊断状态及冻请求重试。** 不发送假定有效的 max_tokens/max_iterations body 字段；不将 202、stop accepted 或 interrupted 当作执行静止 / 任务成功。
- [ ] **Step 4: 重跑 HTTP transport 测试与宿主持久存储集成。**
- [ ] **Step 5: 提交 `feat: integrate public durable Hermes runs`。**

## Task 5: 证据型自我模型

**Files:** Create `self_model.py`, `tests/test_self_model.py`.

**Interfaces:**
- `SelfModel(ledger:Ledger, base:Path).refresh()->dict`、`.snapshot()->dict`、`.restore(version:int)->dict`。
- snapshot 包括 schema / version / evidence revision，按领域和执行 context 分组的 verified samples、success、failure、unknown、blocked、first_attempt_success、eventual_success、置信度均值 / Brier / ECE、active commitments 与来源明确的策略假设；目标级与尝试级统计分开，ECE 沿用现有十桶定义。
- `expected_success(domain:str, context:dict|None=None)->float` 使用有分母的 `(success+1)/(verified+2)` 作为选择辅助，标注估计与有限样本；无证据时 0.5，不能宣称实际能力已被证明。
- 原子导出 `$HERMES_HOME/zhulong/self_model.json`，版本真源为 Ledger；restore 不改动历史 evidence 或 goal outcome。

- [ ] **Step 1: 写失败测试。** 无样本为未知，未知 / 受阻 / 已有产物不计能力成功，重复回执只结一次，缺单类标签不伪造错误区分指标，回退保留 evidence；首次 / 累计区分：

```python
assert snapshot['domains']['code']['verified_samples'] == 1
assert snapshot['domains']['code']['first_attempt_success'] == 0
assert snapshot['domains']['code']['eventual_success'] == 1
assert snapshot['domains']['code']['confidence_on_error'] is None
```

- [ ] **Step 2: 运行 `python3 -m unittest discover -s tests -p 'test_self_model.py' -v`，确认失败。**
- [ ] **Step 3: 从可信 evidence 与终态生成去重快照。** 目标级预测对最终可信结果结算一次；运行前提与具体产物不外推成无限能力；未经核验的反思不成为事实。
- [ ] **Step 4: 重跑测试及原子导出 / reopen / restore 故障用例。**
- [ ] **Step 5: 提交 `feat: ground the self model in verified outcomes`。**

## Task 6: 自主认知与恢复循环

**Files:** Create `autonomy.py`, `tests/test_autonomy.py`.

**Interfaces:**
- `LLMPlanner(llm, budget).plan(observations:list[dict], self_model:dict, policy:dict)->list[dict]`：原生 complete_structured（max_tokens=1600、timeout=45、purpose='zhulong.autonomy.plan'），仍经本地严格校验。
- `Controller(ledger:Ledger, policy:dict, planner, runs:RunsClient, verifier:Verifier, model:SelfModel, clock=time.time)`。
- `tick()->dict`、`status()->dict`、`pause()->dict`、`resume()->dict`、`cancel(goal_id:str)->dict`；单 tick 新派发最多一次 / 合成最多 max_candidates，网络与模型调用有界且在写锁外。
- `start(interval_seconds:int=15)->None`、`stop()->None`：受 stop_event 控制的单后台线程，避免重复 start；插件卸载停止新 tick，不主动释放尚未静止的执行占额。
- Ready 选择依次考虑既有承诺 / 期限，再按 expected_benefit 与相关 verified history 的 expected_success，结合剩余预算 / active 名额可行性，稳定 tie-break；已有 submission 总先恢复。源处理成功才记 fingerprint；失败最多 max_attempts 次并冷却 60 秒，之后等待相关变化。

- [ ] **Step 1: 写失败测试。** 三领域由事实而非现成任务生成候选，各经同一验收闭环；未变化输入重复 tick 零新增 planner 调用；已有产物不派发；缺凭据 / 坏模型 JSON / 无 verifier 不成功。

```python
assert planner.calls_after_unchanged_tick == planner.calls_before
assert controller.status()['required_human_interventions'] == 0
assert ledger.get_goal(goal_id)['state'] != 'succeeded'  # 只有助手文字，无证据
```

另测：模型历史改变选择；最终尝试 / day cap=0 / pause 后仍对账；身份变化 / replay horizon 耗尽为 unknown；interrupted 后迟到写入不触发替代 run；真实未知占额阻止超 max_active；其他 goal 的观察 / 核验仍继续。
- [ ] **Step 2: 运行 `python3 -m unittest discover -s tests -p 'test_autonomy.py' -v`，确认失败。**
- [ ] **Step 3: 实现 observe → synthesize → accept → submit/recover → verify → learn。** 有界调用间续租，长步骤使用租约心跳；所有落盘仍校验当前所有权。人工不是分支条件；无安全重试证据则 unknown，待恢复条件 / 其他工作；pause 不阻断恢复，cancel 不提前归还不确定名额；策略假设保留来源 / 范围。
- [ ] **Step 4: 重跑循环测试及任务来源、反馈启用 / 禁用对照，确认确实有自动成功工作而非全部受阻。**
- [ ] **Step 5: 提交 `feat: close the autonomous planning and recovery loop`。**

## Task 7: 插件、安装与真实验证

**Files:** Modify `__init__.py`, `commands.py`, `reflect.py` 调度接线、`plugin.yaml`, `scripts/install.sh`, `README.md`, `SPEC.md`; Create `tests/test_plugin_autonomy.py`, `tests/test_host_smoke.py`, `scripts/host_smoke.py`, `scripts/live_autonomy_smoke.py`, `examples/autonomy-config.json`, `.github/workflows/tests.yml`.

**Interfaces:**
- `build_commands(..., autonomy=None, self_model=None)` 增加 model / autonomy 命令，旧参数位置兼容。
- `zhulong_model` 只读；`zhulong_autonomy(action='status'|'goals'|'tick')` 无直接评分 / 成功 / 验收修改入口。总计 11 hooks、4 tools、1 command。
- controller 初始化失败仍能加载原观测 / 校准；后台控制 tick 与 observer 分离，遵守 scheduler / env 开关，并能恢复多个实例。通过宿主公开 `ctx.on_unload` 注册 controller.stop 和 S4 stop_event；S4 调度等待改为 Event.wait，不能留下卸载后的无限线程。
- host smoke 接受显式 `--hermes-root`，使用临时 profile，验证元数据私密标记不泄露、旧功能及新工具。live smoke 有限执行、实际 provider/model/usage 及机械证据，凭据通过 env，绝不写正文 / 命令行。

- [ ] **Step 1: 写失败插件测试。** 缺 ctx.llm / 无效 autonomy config 仍有旧 hooks；新命令 / 工具只暴露允许操作；安装后的所有模块可加载；11/4/1；开关无后台模型调用，两个实例不突破限额；unload 与重复 start 不留下多余循环，stop 后无新 tick。
- [ ] **Step 2: 运行 `python3 -m unittest discover -s tests -p 'test_plugin_autonomy.py' -v`，确认未接线导致失败。**
- [ ] **Step 3: 接线并升至 0.4.0。** 安装复制全部模块；示例配置仅含虚构工作数据 / 环回端点 / env 名，身份版本维护规则、已知 quiescence 限制写入 README；SPEC 追加批准的升级决策，保留历史冻结表。CI 在 ubuntu-latest 使用 actions/checkout@v4、actions/setup-python@v6，Python 3.11/3.12/3.14，contents:read，跑标准库 suite。
- [ ] **Step 4: 执行全 suite、固定 PM Python3.14 宿主 smoke及有限真实 DeepSeek 测试。** `tests/test_host_smoke.py` 在未设置 HERMES_AGENT_ROOT 时显式 skip，CI 不假装安装了宿主；本地显式运行 host_smoke。分别验证模型合成和 Hermes 真实工具产物；控制 profile 有有限 agent.max_turns / provider timeout 配置和测试进程总 deadline，记录已执行测试及限度，不虚构 API 的请求级 token / 步数限额。真服务器进程只属于测试，结束时清理；未执行的长期 / 全领域能力不报通过。更新并实测 `/workspace/.cloud-onboarding/install.sh` 与 `START.md` 的模块列表 / smoke，使用 onboarding 配置工具保存完整安装及启动说明，不提交宿主或运行数据。
- [ ] **Step 5: 提交 `feat: ship Zhulong autonomous core v0.4`。**

## Task 8: 独立审查、PR 与合并

**Files:** 修改仅限审查发现涉及的代码 / 测试；新增 PR 说明临时文件，不提交凭据或运行数据。

- [ ] **Step 1: 收集新鲜验证结果。** `source /workspace/.cloud-onboarding/env.sh` 后执行完整 unittest 与 `zhulong-python scripts/host_smoke.py --hermes-root /workspace/.cloud-onboarding/dependencies/hermes-agent`，检查 `git diff --check`、提交范围与秘密 / 运行数据边界。
- [ ] **Step 2: 用独立代码审查者检查整分支。** 对照批准规格、五项 Review Focus、实际故障测试及研究限制；处理有证据的问题，重跑涉及测试。固定被审查的完整 HEAD SHA。
- [ ] **Step 3: 推送分支，创建 PR。** 使用写入临时文件的真实描述与 `gh pr create --body-file`；描述最终行为、研究依据、验证结果及实际限制。创建后立即通过 Codex attach_artifact 关联 URL。
- [ ] **Step 4: 检查 PR diff、CI、合并状态和独立审查结果。** 分支保护详情 API 当前返回 403，不能据此声称无保护；以 GitHub 实际规则与合并结果为准，不使用 admin 绕过。审查后有新提交则复核受影响范围与最新 HEAD。
- [ ] **Step 5: CI / 审查通过后按用户已有授权合并。** 使用 `gh pr merge --squash --match-head-commit <reviewed-sha>`，保留分支，不丢弃工作。确认 PR merged 与远端 main 包含结果，再同步本地；如平台操作被拒绝，报告具体操作和原因，不声称已合并。

## Plan Self-Review

规格 §1–3 对应 Task 3/6/7；§4 对应 Task 1/2；§5 对应 Task 4/6；§6 对应 Task 3；§7 对应 Task 5/6；§8–9 对应 Task 7；§10 对应全部测试及 Task 8。所有五项 Review Focus 已落到具体任务测试。恢复计数 / auth affinity / uncertain occupancy 不以模型判断代替。

本版不包含独立 OS 沙箱、全部真实个人事务连接、长期 soak 或控制内核自动晋升；这些与已批准规格一致。计划执行方式尚待选择；建议 Native，因为核心接口相互依赖，先由同一执行者完成 TDD，再进行整分支独立审查。
