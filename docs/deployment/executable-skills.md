# 可执行程序技能（v0.8）

沿用 [受监督部署](supervised-runtime.md)。默认没有技能清单，不触发程序生成。把 [配置示例](../../examples/executable-skills-config.json) 中的绝对工作路径替换为授权目录；源事实直接位于工作目录顶层且只有一个硬链接。源 JSON 示例是 `{"observations":[1,2,3]}`，输出验收独立检查 `sum == 6`。

可信清单位于控制面 `autonomy.executable_skills`，不能由 worker 修改。一个清单对应源/领域/完整验收契约/执行身份，以及带版本 digest 的 JSON 功能规范。至少 1 个公开例和 2 个不同的未公开例，总共最多 8。公开与未公开输入不能重复，每个 JSON 输入/期待输出最多 4096 字节、深度最多 32。所有非有限数拒绝。模型只看到公开例；任务状态和自我模型不导出答案。

已静止且机械失败的提交触发候选。每个失败/技能组合最多 2 次合成，45 秒超时，代码最多 6000 UTF-8 字节；合成与规划/提示学习共享 `llm_daily_cap`。程序只支持 Python 标准库、一个 JSON stdin 和一个 JSON stdout。评测镜像必须提前缓存、固定 digest，在受保护部署中与 worker 相同。

评测必须有 Linux 本地 Docker socket 权限和 `/usr/bin/timeout`（GNU coreutils）。每项在新容器执行，只有候选目录 RO，nonroot 1000:1000，network none，cap-drop ALL，readonly root，1 CPU / 128 MiB memory+swap / 16 PID，8 MiB noexec tmpfs。宿主独立比较答案；候选不能修改 checker 或自报通过。正常调用路径的 2 秒 wall-clock 包含 attach 启动，输出共 16 KiB，Docker 日志关闭。调用者被强杀时，客户端超时本身不终止容器；受监督启动、恢复和停止还会取得该部署评测锁，移除其 `zhulong.eval` 容器并确认清理。锁繁忙或清理未知会保留 blocked 状态，不能报告资源已停止；强杀窗口不保证 2 秒内清理。默认每日最多 16 次评测，`skill_daily_evaluations=0` 停止新生成/评测，unknown 不退款；按 UTC 日计数。

评测全部通过且清理确认后，版本 active；上一版本 standby。新请求最多携带一个程序，代码、SHA、范围和测试版本全部冻结并事务复查。原生 skills 保持空 RO；worker 可以在工作目录复制代码、验证 SHA 并通过隔离 terminal 执行。普通绑定和成功结果不证明日常确实运行该程序；它们也不证明相对无技能执行的因果提升。

绑定目标的可靠机械失败保守退役该版本，恢复同范围最近的有效 standby，没有备用则停用该范围的程序。旧版本迟到失败只影响旧版本；旧请求重放保留原代码。暂停、stop 或 learning_enabled=false 不接受新执行，仍结算已静止失败；生成途中暂停仍保存已付费返回的有效代码；已冻结代码恢复评测不再次调用模型。代码/config/清单更新仍必须遵守受监督部署的正常停止和验证流程，不能原地篡改受保护 hash。

只读状态：`/zhulong autonomy skills` 或 `zhulong_autonomy(action="skills")`。生成和发布不能通过公开工具写入，自我模型也只导出范围、版本 hash 和有限状态。v0.7 或未启用捕获的历史目标没有原业务输入，不能重新读取当前源补造历史快照。

## 授权输入和原目标回归

默认不捕获。以下是在完整 `autonomy` 配置上的增量示意，source 和 skill 仍需原有字段：

```json
{
  "input_snapshot_bytes": 8388608,
  "sources": [{"id": "statistics", "input_fields": ["observations"], "persist_input_fields": ["observations"]}],
  "executable_skills": [{"id": "sum-observations", "source_id": "statistics", "contract_id": "sum-report", "replay_origin": true}]
}
```

`input_fields` 授权临时读取，`persist_input_fields` 另行授权持久化，必须是前者的子集：1–32 个唯一顶层标识符，各符合 `[A-Za-z_][A-Za-z0-9_]{0,63}`。不接受点路径；不要选择凭据或不应留存的资料。投影最多 4096 UTF-8 字节、深度 32；严格源 JSON 拒绝重复键、非有限数和缺失字段。输入 hash 覆盖规范投影，不是源文件原始字节。

目标和快照在同一 SQLite 写事务冻结。默认累计 payload 额度 8 MiB，0 停止相应来源的新捕获和规划；已有未决请求仍按原内容对账。额度不计 SQLite/WAL、代码、请求或其他文件，不是 profile 的磁盘硬限制；本版不自动删除被冻结的输入。普通 goals 工具/命令和自我模型仅显示 hash/大小，不导出数据或请求。规划仍可能从最多 2000 字符的授权临时 facts 看到相同值；程序合成只收到描述、公开例和最小失败凭据，不收到冻结原输入及其期待字段。

`replay_origin` 默认 false，true 仅适用于捕获已启用的 source 和 `json_equals` 契约。输入不同最多追加 1 个原例（总计最多 9）；输入相同复用该 case，并同时保持完整输出和原字段条件。缺快照记为 `replay_unavailable`，基础期待字段与原条件冲突记为 `spec_conflict`，两者在付费生成前阻止工作。发布事务再次核对当前清单/输入规则、原提交、输入/契约 hash、评测计划 digest、全部案例和清理确认；自报通过不能晋升。

候选 stdout 使用严格 JSON；字段通过点路径访问 object 后 canonical 精确比较，`true`/`1` 与 `6`/`6.0` 不等。原例只证明这份输入上的字段后置条件，不重现路径、`require_change`、副作用、环境、推理或失败根因。此处的严格 JSON 不改变旧文件核验器的解析规则。

有限付费验证命令：

```bash
source /workspace/.cloud-onboarding/env.sh
zhulong-python scripts/supervised_runtime_smoke.py \
  --hermes-root /workspace/.cloud-onboarding/dependencies/hermes-agent \
  --hermes-command /workspace/.cloud-onboarding/bin/hermes \
  --image python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 \
  --paid --skills --replay --report /tmp/zhulong-native-replay.json
```

`--replay` 依赖 `--paid --skills`；旧命令仍可运行。验证使用明确标注的合成无输出失败夹具，真实 DeepSeek 生成程序，并验证独立案例和原例字段。runner 各读取程序/规范输入一次，核验 SHA 后执行同一份程序 bytes、提供同一份输入 bytes。只读原生库核对 Runs fingerprint、session、精确 foreground terminal command、call ID 对应成功结果和严格 typed 输出，随后独立机械验收产物、重放并停止。原失败输入和新目标输入可能不同，各自 hash 单独报告；该有限审计不强制证明所有日常请求实际使用了程序。主执行 token 不包含辅助生成费用，不能等同总成本。

独立审查记录见 [审查与修复](../research/2026-10-10-v0.7-review.md)。Docker daemon 是可信控制面；客户端超时不证明 daemon 已取消迟到操作，尚未进行此类故障注入或长期浸泡测试。非监督手动调用的父进程被强杀后，需要后续评测恢复清理。
