# 可执行程序技能（v0.7）

沿用 [受监督部署](supervised-runtime.md)。默认没有技能清单，不触发程序生成。把 [配置示例](../../examples/executable-skills-config.json) 中的绝对工作路径替换为授权目录；源事实直接位于工作目录顶层且只有一个硬链接。源 JSON 示例是 `{"observations":[1,2,3]}`，输出验收独立检查 `sum == 6`。

可信清单位于控制面 `autonomy.executable_skills`，不能由 worker 修改。一个清单对应源/领域/完整验收契约/执行身份，以及带版本 digest 的 JSON 功能规范。至少 1 个公开例和 2 个不同的未公开例，总共最多 8。公开与未公开输入不能重复，每个 JSON 输入/期待输出最多 4096 字节、深度最多 32。所有非有限数拒绝。模型只看到公开例；任务状态和自我模型不导出答案。

已静止且机械失败的提交触发候选。每个失败/技能组合最多 2 次合成，45 秒超时，代码最多 6000 UTF-8 字节；合成与规划/提示学习共享 `llm_daily_cap`。程序只支持 Python 标准库、一个 JSON stdin 和一个 JSON stdout。评测镜像必须提前缓存、固定 digest，在受保护部署中与 worker 相同。

评测必须有 Linux 本地 Docker socket 权限和 `/usr/bin/timeout`（GNU coreutils）。每项在新容器执行，只有候选目录 RO，nonroot 1000:1000，network none，cap-drop ALL，readonly root，1 CPU / 128 MiB memory+swap / 16 PID，8 MiB noexec tmpfs。宿主独立比较答案；候选不能修改 checker 或自报通过。正常调用路径的 2 秒 wall-clock 包含 attach 启动，输出共 16 KiB，Docker 日志关闭。调用者被强杀时，客户端超时本身不终止容器；受监督启动、恢复和停止还会取得该部署评测锁，移除其 `zhulong.eval` 容器并确认清理。锁繁忙或清理未知会保留 blocked 状态，不能报告资源已停止；强杀窗口不保证 2 秒内清理。默认每日最多 16 次评测，`skill_daily_evaluations=0` 停止新生成/评测，unknown 不退款；按 UTC 日计数。

评测全部通过且清理确认后，版本 active；上一版本 standby。新请求最多携带一个程序，代码、SHA、范围和测试版本全部冻结并事务复查。原生 skills 保持空 RO；worker 可以在工作目录复制代码、验证 SHA 并通过隔离 terminal 执行。普通绑定和成功结果不证明日常确实运行该程序；它们也不证明相对无技能执行的因果提升。

绑定目标的可靠机械失败保守退役该版本，恢复同范围最近的有效 standby，没有备用则停用该范围的程序。旧版本迟到失败只影响旧版本；旧请求重放保留原代码。暂停、stop 或 learning_enabled=false 不接受新执行，仍结算已静止失败；生成途中暂停仍保存已付费返回的有效代码；已冻结代码恢复评测不再次调用模型。代码/config/清单更新仍必须遵守受监督部署的正常停止和验证流程，不能原地篡改受保护 hash。

只读状态：`/zhulong autonomy skills` 或 `zhulong_autonomy(action="skills")`。生成和发布不能通过公开工具写入，自我模型也只导出范围、版本 hash 和有限状态。旧账本未冻结原业务输入，因此公开回归例不能当作任意原失败的精确重放。

有限付费验证命令：

```bash
source /workspace/.cloud-onboarding/env.sh
zhulong-python scripts/supervised_runtime_smoke.py \
  --hermes-root /workspace/.cloud-onboarding/dependencies/hermes-agent \
  --hermes-command /workspace/.cloud-onboarding/bin/hermes \
  --image python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 \
  --paid --skills --report /tmp/zhulong-native-skills.json
```

验证明确使用合成的无输出失败夹具；真实 DeepSeek 生成程序，经 3 个独立 case 评测后，新目标执行。只读原生持久库核对 Runs fingerprint、session、精确 foreground terminal command、call ID 对应成功结果和代码 SHA，随后独立机械验收产物、重放并停止。主执行 token 统计不包含辅助生成费用；一次成功不建立通用智能。常驻服务和长期运行另需部署验证。

独立审查记录见 [审查与修复](../research/2026-10-10-v0.7-review.md)。Docker daemon 是可信控制面；客户端超时不证明 daemon 已取消迟到操作，尚未进行此类故障注入或长期浸泡测试。非监督手动调用的父进程被强杀后，需要后续评测恢复清理。
