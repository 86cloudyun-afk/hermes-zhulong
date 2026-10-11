# 五个自主智能研究方向的离线复现实验

这些脚本用于 [2026-10-11 研究](../../2026-10-11-autonomy-frontiers.md)。它们不调用模型、不读取实际 profile、不开生产任务、不安装依赖；实际产品代码只在临时 SQLite/文件夹具中被调用。根节点在基线 `deffc94e0c30ef3b20481ff6aaf9af5687371ef5` 独立重跑五个脚本，均退出 0。另一次固定宿主与真实 Docker 完整基线测试为 235/235，0 skip。

从仓库根目录运行，唯一位置参数是**输出目录**。输出写到该目录，不写入研究源码目录；已有同名输出会覆盖。选择新的目录以保留旧证据。

```bash
source /workspace/.cloud-onboarding/env.sh
FRONTIERS_OUT=/tmp/zhulong-frontiers-reproduction
zhulong-python docs/research/experiments/autonomy_frontiers/execution_probe.py "$FRONTIERS_OUT"
zhulong-python docs/research/experiments/autonomy_frontiers/root_cause_probe.py "$FRONTIERS_OUT"
zhulong-python docs/research/experiments/autonomy_frontiers/causal_gain_demo.py "$FRONTIERS_OUT"
zhulong-python docs/research/experiments/autonomy_frontiers/metacognition_probe.py "$FRONTIERS_OUT"
zhulong-python docs/research/experiments/autonomy_frontiers/publication_probe.py "$FRONTIERS_OUT"
zhulong-python docs/research/experiments/autonomy_frontiers/adapter_atomicity_probe.py "$FRONTIERS_OUT"
```

其他环境可用 Python 3.11+ 代替 `zhulong-python`；不需要 Docker、Hermes 宿主或 API key。整套基线测试的实际 Docker/宿主运行与这些纯离线探针分别记账。

| 脚本 | 输出 | 实际操作与允许结论 |
|---|---|---|
| `execution_probe.py` | `probe-results.json` | 调用实际 Ledger 的代次认领，读取实际 Verifier；独立模拟未 fencing 效果端及事务型幂等适配器。确认代次写入和解析差距；适配器只是协议演示 |
| `root_cause_probe.py` | `experiment-results.json` | 可信求和程序的两项已知故障，36 个因子运行，另做失败输入缩减。说明交互/遮蔽与 1-minimal 的界限，不诊断真实模型 |
| `causal_gain_demo.py` | `offline-protocol.json`、`offline-outcomes.json`、`offline-analysis.json` | 384 个模拟任务对、随机顺序、固定种子、配对检验/区间与四类坏记录拒绝。没有 Hermes 因果提升证据 |
| `metacognition_probe.py` | `metacognition_probe.json` | 实际 `_metrics` 接收三组各四条合成观测；研究计算 AUROC2。核对 availability 含义，不是实际模型或意识实验 |
| `publication_probe.py` | `publication-probe.json` | 既有 ReplayTests 夹具调用实际发布 SQLite 代码，4096 个守卫分区、六负例、暂停入口对照和 unknown 恢复。替换 Docker runner/cleanup；不是形式证明 |
| `adapter_atomicity_probe.py` | `adapter-atomicity-check.json` | 独立提取实际示例的 apply 函数体，在 fence 读取后用第二 SQLite 连接尝试更新；验证查询已在写事务内、更新被阻塞且提交后旧 token 被拒绝。只覆盖一个受控时序 |

提交的 [实验结果](../../evidence/2026-10-11-autonomy-frontiers/) 是原基线观测。完整模拟 outcomes 可从代码重生；其 canonical SHA 在 analysis 中。每个输入、代码或报告 hash 的含义以专题正文为准；绑定工件不等于证明未见输入或完整流程。

独立审查后，事务示例加入显式 `BEGIN IMMEDIATE`，并收紧发布探针对拒绝后状态变化的失败判据。上述第六个探针对原示例退出 1、对修复示例退出 0；发布判据的状态变更注入由未检出变为检出。重跑两项改动脚本与补充证据见 [审查闭环](../../2026-10-11-frontiers-review.md)。实验索引分别保存原基线与修复后研究源码的 hash，不把修改过的研究脚本冒称为原 commit 内容。

未来版本的主验收可能修复重复键，或更改暂停语义；相应探针输出可以变化。比较 Git HEAD 与 [验证索引](../../evidence/2026-10-11-autonomy-frontiers/verification.json) 的源码 hash 后再解释，不能把新版本的结果冒称本轮证据。脚本不会把已观察到的解析差距注册成要求永远保留的产品回归测试。
