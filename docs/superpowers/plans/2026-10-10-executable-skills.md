# Executable Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** 让已有自主循环独立验证、发布、复用和回退不可变可执行 Python 程序。

**Architecture:** 私有 SQLite 保存候选、发布版本、来源及冻结评测凭据。独立 Docker 只运行候选，控制面比较 JSON；跨进程锁贯穿评测生命周期。冻结请求携带已评测程序，保留原生空 skills 挂载。

**Tech Stack:** Python 3.11+ stdlib、SQLite、Linux flock、已有 Docker 和固定原生 Hermes；不新增依赖。

**Spec:** docs/superpowers/specs/2026-10-10-executable-skills-design.md

## Global Constraints

- 模型预算沿用 Budget.take；2 次/失败/技能，45 秒；程序 6000 UTF-8 字节，完整请求 16384 字节。
- 最多 4 清单、1 公开/2 未公开起、最多 8 case；JSON 各 4096 字节；image digest 固定，protected worker/evaluator 相同镜像。
- 候选不在宿主执行；独立非 root/no network/read-only 容器，1 CPU/128 MiB memory+swap/16 PID/8 MiB tmpfs，2 秒、16384 输出字节。
- 云 checkout 已隔离，不另建 worktree；用户已有研发和 PR 合并授权，不重复请求阶段批准。

## Review Focus

- 崩溃在 Docker 创建中：继承锁与 durable token 阻止迟到容器和并行评测。
- 清理未知：不把资源已静止作为事实，不发布也不启动下一次评测。
- 活跃版本换代：旧提交失败只退役其绑定版本，新提交事务拒绝旧绑定。
- 测试或身份漂移：不能检索和发布到另一范围，隐藏答案不进入合成器输入。
- stopped/paused 或耗尽预算：保留已付费代码，不再次生成；复用退役仍结算。

### Task 1: Trusted evaluator

**Files:** Create skill_evaluator.py, tests/test_skill_evaluator.py.
**Interfaces:** `validate_skills(raw, sources) -> list[dict]`; `DockerEvaluator(ledger_path)`; `locked() -> context manager bool`; `cleanup() -> bool`; `evaluate(code, task, token, admissible) -> dict`.

- [x] 写清单非法值、host 独立比较、隐藏值不进 stdin、Docker 限制、锁竞争/清理未知的失败测试；运行 unittest 观察缺失功能。
- [x] 实现规范验证、锁及固定 Docker 命令、逐 case stdin/stdout、有界清理和 hash 报告；运行针对测试与完整 suite。
- [x] 提交 evaluator 与测试。

### Task 2: Durable skill publication and rollback

**Files:** Create skill_store.py, tests/test_skill_store.py; modify autonomy_store.py.
**Interfaces:** `SkillStore(ledger,tasks,identity)`, `sync(now)`, `claim(now)`, `begin(job,now)`, `freeze(job,code,now)`, `finish(job,report,now)`, `defer(job,now,reason)`, `owned(job,now)`, `retrieve(goal,identity)`, `summary()`; `valid_bindings(connection,goal,identity,request)` atomic admission helper.

- [x] 写静止证据、去重、2 次上限、重启 fencing、immutable、过期评测重用、active/standby/retired 回退、旧请求/测试/身份漂移测试；运行观察 RED。
- [x] 实现 additive tables、证据扫描、冻结候选、评测发布事务；新绑定只允许 active，重放沿用已有提交；运行针对测试和完整 suite。
- [x] 提交 ledger 与测试。

### Task 3: Autonomous generation and native execution

**Files:** Create skill_learning.py, tests/test_skill_learning.py; modify autonomy_checks.py, autonomy.py, __init__.py, runtime_policy.py, commands.py, plugin.yaml, scripts/install.sh; extend tests/test_plugin_autonomy.py and runtime policy tests.
**Interfaces:** `SkillLearner(store,llm,budget,evaluator,clock).tick(now,admissible)`; Controller optional `skills`, `skills_status()`; read-only autonomy action `skills`.

- [x] 写共享预算/停止/隐藏清单/独立评测失败不发布/恢复不重复模型、请求冻结和 protected image 错配测试，运行观察 RED。
- [x] 接入 learning 和状态，控制 recovery 先执行；保留空原生 skills、只带单一已评测代码；所有新增模块纳入安装及 protected hashes；升级 v0.7.0。
- [x] 完成真实 Docker 及原生 paid smoke，结果持久化，不声称精确故障回放或因果收益；完整 suite 后提交。

### Task 4: Review and delivery

**Files:** Research, deployment, review/evidence docs；云环境 setup 位于 checkout 外。

- [x] 更新研究和操作文档；fresh whole-branch reviewer 独立审查，逐条裁定；Important/Critical 一次 RED→GREEN 修复并完整 suite。
- [ ] PR、精确 commit CI；审查后 squash 合并；同步 main 并确认 tree 与已验证代码一致。
- [ ] 运行 installer 和 native offline smoke，完整 checkout discovery 后保存 exact main 的环境配置草稿；配置发布仍由产品负责。

交付进度以 [PR #4](https://github.com/86cloudyun-afk/hermes-zhulong/pull/4) 和云环境配置草稿为准；后两项在合并及保存完成后由交付记录结算，计划文件不要求再次修改 main。
