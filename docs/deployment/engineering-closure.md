# 五专题工程与历史问题清单（v0.9）

这份清单区分已实现接口、实际验收和仍需外部条件的目标。真实 Hermes 的能力证据见版本对应的验证记录；本地夹具、Docker 程序评测、有限模型检查和付费原生任务分别计数。

## 已实现的工程机制

| 研究线/问题 | 产品实现 | 验收入口 | 保证范围 |
|---|---|---|---|
| 主 JSON 验收与严格回放不一致 | `autonomy_checks.py` check_version=2 | JSON 重复键、NaN/Infinity/指数溢出、布尔/数值、深度回归 | 整文件严格解析，旧收据不重写；深度 32 是本版明确限制 |
| 固定答案可伪装完成 | `work_reference.py` / `json_reference` | 三种变量业务输入及原生执行审计 | 私有参考计算整份结果；不保证任意自然语言任务 |
| 步骤依赖、崩溃重做 | `workflow.py` + Controller | DAG/事务/并发/重启/取消测试 | 可信有界 DAG、每步 Hermes 子目标、局部 safe_retry；没有自由生成无限重规划 |
| 外部效果与 run 幂等混淆 | `workflow_effects` / `workflow_outbox` | 双意图冲突、事务回滚、重复恢复 | 本地 outbox 一次写入；远程效果与投递继续明确 unknown/unavailable |
| 解释文字被当作根因 | `diagnostics.py` | 独立 Docker 双因素、负对照、原输入重放 | 配置干预的有限支持；模型叙述只是假设 |
| 未知实验无限重试/关闭配置丢恢复 | 持久实验 reservation/quiescence | 三次尝试、零额度清理、配置移除恢复 | 实际评测次数计预算；清理未知阻止新派发，旧代码/收据保留 |
| 把相关成功当作因果提升 | `causal_trial.py` | 冻结协议/作用域/单机制/固定 N/全部分母/时间与成本记录测试 | 协议和业务成功率端点分析已实现；真实配对 execution adapter 尚未实现，端点结论需足量可信独立配对样本；经济收益另需完整成本 |
| 仅离线测试冒充 Hermes 工作能力 | `scripts/native_work_acceptance.py` | `--paid` 真实 LLM 发现目标、Runs、Docker terminal、业务产物审计 | 三个有限业务样例；不证明所有用户任务或长期收益 |
| availability 被当成错误识别能力 | `self_model.py` | 正序/反序/常数 AUROC2、类别与 coverage-risk | 保留兼容 availability 字段，另报告质量、分母和范围 |
| 重试复用旧目标预测 | `metacognition.py` + Ledger | 派发前冻结/陈旧捕获/后验绑定拒绝 | 同范围尝试的历史估计、真实前置复查；不声称内省体验 |
| 暂停与技能发布竞争 | SkillStore 同事务 pause 守卫 | 两种双连接次序、退役与备用恢复 | pause 返回后无新正向激活；旧有效结果和安全负向结算保留 |
| 状态转换可伪造终态 | Ledger 终态守卫 + assurance | unknown→failed/succeeded 反例 | 新终态只由机械收据产生；已有真值的运行跟踪允许 |
| 仅布尔守卫枚举冒充整体正确性 | `assurance.py` | 独立 BFS、八种错误变体、真实事务轨迹 | 显式有限界内不变量；不覆盖诊断预算、任意外部副作用或无限运行 |
| 大旧账本被单一快照上限阻塞 | 分页初始 checkpoint | 6500 目标、超过 1 MiB、漏页拒绝 | 不遗漏历史投影；没有以截断来制造有效轨迹 |
| 业务 JSON 与 manifest 封套深度混淆 | skill_evaluator 业务/封套分离 | 深度 32 业务与传输包装 | 各业务值单独验证；封套不压缩业务有效深度 |
| 已验收但未静止的 run 不响应取消 | Controller 取消先于真值跟踪 | 产物成功/执行 interrupted 的取消回归 | 发送停止，保留成功真值与未知 quiescence，不能冒充即时消除副作用 |

## 部署使用

先按 [受监督部署](supervised-runtime.md) 安装固定宿主、官方 PM Python、Docker 和摘要固定镜像，再创建独立授权目录。插件安装不会自动开启自主运行；必须有真实来源、任务方向和契约。`json_reference` 来源显式设置 `persist_input_fields`，业务内容只冻结到私有账本。

以下是 `autonomy.sources` 中单个来源的配置示例；路径需位于预先授权的 `workspace_roots`。`input_fields` 用于观察变化，`persist_input_fields` 明确允许冻结的顶层字段。

```json
{
  "id": "business-facts",
  "domain": "personal",
  "path": "/absolute/authorized/work/tasks.json",
  "direction": "依据任务数据生成完整工作量汇总",
  "input_fields": ["tasks"],
  "persist_input_fields": ["tasks"],
  "contracts": {
    "business-report": {
      "type": "json_reference",
      "path": "/absolute/authorized/work/report.json",
      "reference_id": "workload_summary_v1",
      "reference_version": 1,
      "require_change": true,
      "safe_retry": true
    }
  }
}
```

该来源文件的业务结构是 `{"tasks":[{"id":"a","team":"ops","minutes":20,"done":false}]}`。其他内置规则为 `ticket_priority_v1`（`tickets`）和 `source_index_v1`（`sources`）；完整字段、类型和算法见 [可信参考函数](../../work_reference.py)。每份冻结业务输入最多 4096 UTF-8 字节、32 层，每个列表最多 64 条记录。规则 ID 不能指定任意代码或自然语言评分。执行请求携带规则与授权输入；核验器在私有侧计算整份答案，严格检查字段和类型。缺少有效冻结输入、绑定不符或版本不支持时保留 unknown。

工作流清单示例（位于 `autonomy` 对象内，需为该来源另行配置所引用的全部契约）：

```json
{
  "workflows": [{
    "id": "report-pipeline", "source_id": "business-facts", "contract_id": "final-report",
    "steps": [
      {"id": "prepare", "contract_id": "prepared", "objective": "生成约定的准备产物", "effect_mode": "opaque_nonretryable"},
      {"id": "report", "contract_id": "business-report", "objective": "计算并生成业务报告", "depends_on": ["prepare"], "effect_mode": "local_outbox"}
    ]
  }],
  "monitoring": {"enabled": true, "mode": "normal", "threshold": 0.6, "max_rechecks": 1},
  "diagnostic_daily_evaluations": 2
}
```

所有 contract ID 必须在同一来源预先配置。`opaque_nonretryable` 不自动重试；`local_outbox` 记录完成通知元数据而不发信。`read_only` 是可信计划对效果的分类，不是单独的 OS 只读权限；实际权限仍来自受监督部署，不能用标签代替隔离。内部步骤契约不会交给规划器作为可跳过依赖的独立目标。

诊断需要 `diagnostics` 可信清单：关联已配置 skill_id，1–3 个因素，各非空组合一份冻结代码，另有负对照。该代码只能在已有隔离评测器运行，不能变成宿主 argv。没有可信原失败、原输入或原回归时，显示 unavailable，不靠模型补造。

```text
/zhulong autonomy status
/zhulong autonomy experience
/zhulong autonomy skills
/zhulong autonomy workflows
/zhulong autonomy diagnostics
/zhulong autonomy assurance
```

最后一个命令实际运行固定界的模型检查和真实账本轨迹验证；普通 status 只报告已运行的检查，不制造通过记录。默认模型取 2 个目标、2 个租约代次、预算 2、深度 8、同时 1 个 run，当前枚举为 1236 个状态、3811 个转移，在该界内未发现反例；八种守卫错误变体均有反例。有限模型不覆盖任意文件/网络/外部效果、诊断预算或无限执行。

插件保持 11 个 hooks、4 个工具和 1 个命令入口。`zhulong_autonomy` 的 8 个 actions 是 `status`、`goals`、`tick`、`experience`、`skills`、`workflows`、`diagnostics`、`assurance`，没有直接评分或改验收接口。`/zhulong autonomy` 另提供 `pause`、`resume` 和 `cancel <id>`。

真实有限工作验收（会产生模型消耗）：

```bash
zhulong-python scripts/native_work_acceptance.py \
  --root /absolute/new/private/acceptance \
  --hermes-root /workspace/.cloud-onboarding/dependencies/hermes-agent \
  --hermes-command /workspace/.cloud-onboarding/bin/hermes \
  --image python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 \
  --allocations 3 --paid
```

不传 `--paid` 仅登记协议、输入和未运行分母，绝不算完成能力验收。每个分配保留独立私有 profile、失败收据、产物、native 数据库和日志；分享时只导出脱敏验证摘要。不能将缺失计费用量写成零费用。

有限 pilot 的新入口在部署启动前将可信 runner 写入原生只读缓存，以完整 SHA 纳入部署保护，并在独立 profile 中只预授权 `python3 /root/.hermes/cache/generated/zhulong-work-runner.py` 这一条精确命令。它读取并执行相同的候选代码与冻结输入字节，不携带参考答案；完整业务验收、原生轨迹审计及宿主 deny/hardline 守卫继续生效。实际 Docker 使用显式 `/root` tmpfs mode=711，owner 0；uid 1000 只能穿越、不可列举/写入该目录，来源与缓存仍只读。正式零 provider/gateway probe 已完成精确执行与清理；干净代码 `0f5841ebfcaa14325638cf199d8bb343bb9d1e59` 的新三任务真实验收 C 为 3/3 成功，各项业务/原生审计/静止/清理全 true。原内联 runner 和前三个探测的不完整结果分别保留，完整分母、用量范围与代码绑定见 [v0.9 验证记录](../research/2026-10-11-v0.9-validation.md)和[审查记录](../research/2026-10-11-v0.9-review.md)。

验收报告的 `auxiliary_calls` 只统计插件 `llm_daily` 预算表，native guardian 等额外调用不在该字段内；它不能作为所有模型调用或完整成本的分母。

该脚本只运行 `finite_usefulness_pilot`：真实 LLM 从变化输入中发现目标，经 Hermes Runs 和 Docker 工具生成产物，再机械验收与审计原生轨迹。执行或清理未确认时停止后续分配，保留未运行分母。它不能运行 `paired_fixed_n`；后者目前仅有 `causal_trial.py` 的协议、分配账本、外部可信收据资格检查和固定 N 分析，需要另行实现真实同作用域、单机制控制/处理 execution adapter。设计中“由同一工具另行开展足量随机试验”的目标仍未完成。

## 仍需外部条件或持续验证的项目

| 项目 | 已有基础 | 完成条件 |
|---|---|---|
| 真实邮件/日历/工单事务 | 本地草案、stable operation 和 outbox | 明确目标服务/授权凭据、服务的幂等/查询能力、真实回执与对账适配器；本版不自动发送消息 |
| 原子替换输入文件/外部输入挂载 | 冻结快照与 RO 来源 inode | 可信摄取服务在模型权限之外更新并冻结；当前固定 inode 部署仍不支持运行中替换 |
| 全 profile/work 硬磁盘配额 | 业务快照额度、Docker tmpfs/资源约束 | 支持 project quota 的底层文件系统或独立限额卷；当前 vfs bind mount 无硬配额，软阈值不能替代 |
| daemon 延迟动作与强终止 | owned 容器清理、unknown 保留、取消恢复 | 专项真实 daemon 故障/延迟注入和外层进程管理器验证；不可把 CLI 超时解释成已经静止 |
| 24/72 小时与跨日稳定性 | 有界恢复/预算/故障回归、保留的原生验收 | 实际按相应时间运行及故障记录；短 smoke 不能代替 |
| 自动修改并晋升控制内核 | 代码/config hash 固定、技能候选隔离验证、旧真源保留 | 独立可信构建/测试/发布/回滚服务及产物证明；模型工具目前不能编辑控制内核 |
| 全局严格货币预算 | run/辅助/诊断次数额度、主用量和成本缺失项 | 提供商可核验的完整主/辅助/训练/迟到账单与费用停止机制；次数上限不是金额硬上限 |
| 真实因果提升与经济收益 | paired_fixed_n 业务成功率端点协议与合格收据分析；真实配对 execution adapter 未实现 | 业务成功率端点需要真实控制/处理适配器、同有效作用域的随机分配和足量可信独立配对样本；经济收益/成本效益另需完整可核验费用。有限业务 pilot 不作上述结论 |
| 意识和通用正确性 | 功能元认知与有限不变量 | 可区分理论的可信实验和明确证明对象；不存在可直接发布的“全自我意识”开关 |

早期文档中提及的 dsh/其它宿主、桌面深集成、跨 profile 联邦和公共技能市场原本不在 Hermes 本项目范围，不纳入本版虚构交付。旧版本已修复的 review 问题保留原闭环，不重复列为新发现。
