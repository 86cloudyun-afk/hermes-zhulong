# Frozen Input Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** 让授权的任务输入与可信验收一起冻结，并作为程序发布前的原目标字段回归。

**Architecture:** 同一次观察投影，私有 additive SQLite 原子冻结；请求绑定在派发写事务复查；可信回归计划与发布事务校验独立于模型。

**Tech Stack:** Python 3.11+ stdlib/SQLite、现有 Linux Docker 与固定 native Hermes；无新依赖。

**Spec:** docs/superpowers/specs/2026-10-10-frozen-input-replay-design.md

## Global Constraints

- 默认不捕获；persist_input_fields 为 input_fields 子集，1–32 唯一顶层标识符、各64字符。
- 投影4096 UTF-8 bytes、深度32；input_snapshot_bytes 默认8388608、0关闭；请求16384 bytes。
- 原案例仅 json_equals 字段谓词，基础case最多8+新增原例1；canonical类型精确，严格JSON。
- 生成6000 bytes/45s/2次，共享模型预算及每日评测cap16；不改变v0.7隔离/恢复限制。
- 不复制源全文/聊天/工具/保险库凭据，不输出业务payload到普通状态、self-model或学习提示。
- 已隔离云checkout，使用feature branch，不新增worktree；沿用用户既有研发/PR/审查后合并授权。

## Review Focus

- 源或投影在规划中变化：不能从另一版本补读输入，混合版本拒绝。
- 两连接抢最后额度：最多一份新payload成功，失败无孤立goal或预算消耗。
- 旧目标/非法或消失输入：明确 unavailable，已有未知执行仍用旧请求对账。
- 同输入不同期待与伪造回归报告：付费前冲突阻塞，错误origin或计划digest不发布。
- 新实例改变规则/清单，旧实例迟到发布：当前settings须在事务中重查，普通导出不泄漏数据。

### Task 1: Trusted projections and immutable input binding

**Files:** Create task_inputs.py, tests/test_task_inputs.py; modify autonomy_checks.py, autonomy_store.py, autonomy.py, commands.py, __init__.py, runtime_policy.py, scripts/install.sh.
**Interfaces:** task_inputs.rule_for(source)->dict|None; project(source,parsed)->dict|None; initialize(connection); configure(ledger,sources,cap); bind_goal(connection,goal_id,source_id,revision,binding); binding(connection,goal_id)->dict|None; valid_binding(connection,goal,request)->bool; available(ledger,binding)->bool; summary(ledger)->dict; public_goals(ledger)->list. Ledger.create_goal(...,task_input=None) keyword. Controller captures selected observation input and freezes request.

- [x] 写 test_task_inputs：非法授权/严格JSON、同观察和rule revision、不可变/旧goal不可补写、两连接最后额度、事务失败rollback、篡改请求不花预算、规则移除仍reconcile原提交、planner/本地goals/self-model不泄漏。运行 `zhulong-python -m unittest discover -s tests -p test_task_inputs.py`，Expected缺模块/接口或新行为断言失败。
- [x] 实现上述接口及配置/控制器接入，普通请求默认兼容。运行该测试和 `HERMES_AGENT_ROOT=... zhulong-python -m unittest discover -s tests`，Expected全通过，Docker仅明确skip。
- [x] 提交 input binding 与测试。

### Task 2: Trusted original-goal regression gate

**Files:** Create skill_replay.py, tests/test_skill_replay.py; modify skill_evaluator.py, skill_store.py, skill_learning.py, runtime_policy.py, scripts/install.sh.
**Interfaces:** skill_replay.evaluation_task(task,goal,submission)->dict (private _evaluation_cases, evaluation_digest, origin_replay); trusted replay uses task_input.binding and current-rule metadata. DockerEvaluator.evaluate existing signature; SkillStore.claim returns private augmented task, finish rebuilds same plan in writeTX.

- [x] 写基本case过而原例错、去重并保持完整输出、条件冲突付费前阻止、缺快照unavailable、原数据不进模型、wrong-origin/digest报告、当前settings漂移、暂停/unknown恢复回归测试。运行 test_skill_replay，Expected新功能断言失败。
- [x] 实现 replay_origin 规范与回归计划、独立字段checker、发布事务门槛及状态。运行 targeted +完整suite；实际Docker验证原例failure/去重/unknown不发布，Expected通过。
- [x] 提交 replay gate 与测试。

### Task 3: Native evidence and v0.8 deployment

**Files:** Modify scripts/skill_smoke_evidence.py, scripts/supervised_runtime_smoke.py, runtime_policy.py, scripts/install.sh, plugin.yaml；extend tests/test_skill_smoke_evidence.py, test_plugin_autonomy.py及native/protected policy checks。
**Interfaces:** runner_command(...,input_hash=None) optional frozen-input file mode; audit_native_skill(...,task_input=None) optional binding；--replay依赖--paid --skills。

- [x] 写类型混淆/重复key拒绝、错误input SHA、一次读取后同bytes执行、绑定canonical SHA和原生call/result对应、安装/保护新模块测试；观察RED。
- [x] 实现严格audit与回归native场景，新增模块纳入安装/保护，版本0.8.0。完整真实Docker/native suite，Expected全通过。
- [x] 干净commit做有限真实DeepSeek Flash --replay smoke；Expected认证包含原例与确切程序/输入SHA执行，静止结算，同run重放，停止/清理真实标记。持久化证据与提交。

### Task 4: Review and delivery

**Files:** research/deployment/review/evidence docs，checkout外云setup。

- [ ] 更新研究/操作文档，fresh最有能力 reviewer 一次整分支审查，逐条裁定；Critical/Important一次RED→GREEN修复及全suite，不重新审查。
- [ ] PR附加到任务、精确HEAD CI与审查记录，通过后squash合并并同步main，确认tree相同。
- [ ] managed installer/offline native烟测及19+2安装副本校验；完整workspace发现后保存精确main、install/start并读回。环境发布仍由产品界面执行，交付记录在PR与环境草稿，不再改写main。
