# 烛龙（hermes-zhulong）· 冻结规格 v1.0

**冻结日期**：2026-10-09 ｜ **决策**：YG（方向）+ LCS（设计执行）
**前置研究**：`hermes-awakening-plugin-research-2026-10-09.md`（心理学 × 逻辑学 × 工程学）

## 1. 八项决策（已冻结）

| # | 问题 | 决策 | 来源 |
|---|---|---|---|
| 1 | 命名 | **烛龙 Zhulong**（repo: `hermes-zhulong`；备选花名：照妖镜） | YG 授权 LCS 取中二代号 |
| 2 | 作用面 | **先做 Hermes**（插件随 Hermes 全表面生效：CLI/网关/TUI/Desktop 免费获得）；其他平台与表面后续再研究 | YG |
| 3 | 自我模型是否包含对用户的观察 | **包含，但受限**：仅"工作上下文"子集（时区/时段规律/项目名等），本地存储、显式标记、可用命令查看与删除；不做敏感画像 | LCS 代决 |
| 4 | 反思节奏与预算 | 感知=持续；反思=**每日自动**（会话内 heartbeat 或离线 cron）；探针+周报=每周自动；`ctx.llm` 预算上限 **40 次/日** | LCS 代决（YG：自动） |
| 5 | 写模式 | **自动**，但带可逆性保证：机械字段（统计/时间戳/证据状态）自动写；语义级自我模型变更自动提交但**全量 git 版本化、一键回滚**；红线项（SOUL.md、代码、删除操作）永远只提案待人审 | YG：自动 + LCS 补安全约束 |
| 6 | 自传体 git | **是**：自我模型/叙事自动提交到本地 git（烛龙时段线），周报附 commit 摘要 | LCS 代决（YG：自动） |
| 7 | 探针 | **自动**（每周）+ 手动 `/zhulong audit` 双通道 | LCS 代决（YG：自动） |
| 8 | 开源 | **是**：MIT；仓库从第一天就按开源标准建设（README/SPEC/LICENSE/无秘密/数据与代码分离）；发布时机另定 | YG |

## 2. 自动化矩阵（"自动"的边界）

| 动作 | 模式 | 护栏 |
|---|---|---|
| 事件采集（全部 hooks） | 全自动 | fail-open、元数据级、本地 |
| 统计/聚合 | 全自动 | 无 |
| 校准结算（S3） | 全自动 | 只读现有数据 |
| 反思生成（S4） | 自动（定时） | 预算 40 调用/日、结果进提案区 |
| 自我模型·机械字段 | 自动提交 | git 版本化 |
| 自我模型·语义变更 | 自动提交 | git 版本化 + 周报可见 + `/zhulong revert` |
| 叙事更新 | 自动提交 | 同上 |
| 红线（身份文件/代码/删除） | **仅提案** | 人工审批制 |

## 3. 范围

- **In（Hermes）**：插件本体、日记、命令、S3-S5 全部按本规格推进。
- **Out（后续）**：其它宿主（dsh 等）、桌面仪表盘深度集成、多 profile 联邦、公开技能市场分发。

## 4. 数据与隐私

- 全部数据：`$HERMES_HOME/zhulong/`；代码与数据分离（git 仓库只含代码）。
- 存储红线：不存工具参数/结果/消息正文/prompt 原文；只存元数据。任何升级若触碰此线需重新评审。
- 留存：`ZHULONG_RETENTION_DAYS=90`（可调）。

## 5. 阶段与验收

| 阶段 | 内容 | 退出标准 | 状态 |
|---|---|---|---|
| S0 | 研究（三支柱报告） | 交付 | ✅ |
| S1 | 规格冻结（本文） | YG 决策到位 | ✅ |
| S2 | MVP：观测脊柱 | 事件覆盖、零阻塞、测试通过、真实会话验证 | ✅（v0.1.0） |
| S3 | 校准账：预测-结果对账、Brier/ECE、弃答统计 | 对账可跑、指标存历史 | ✅（v0.2.0） |
| S4 | 反思引擎 + 探针（自动） | 预算内运行 2 周、提案可读 | ✅（v0.3.0） |
| S5 | 自我模型 + `/zhulong model` + 周报 | 对账通过率 ≥90% | ⏳ |

## 6. 开源计划

- MIT（版权：YG 2026）；仓库 `hermes-zhulong`（本地 `/data/workspace/projects/hermes-zhulong`）。
- 发布前检查：无密钥、无个人数据样例、README/SPEC 齐、CI（v0.2 起加 GitHub Actions 跑 unittest）。
- 发布时机：S5 完成后由 YG 拍板（可先私有 mirror）。

## 7. v0.2.0 实现注记（S3 校准账）

- 工具：`zhulong_predict`（登记预测）；`zhulong_calibration`（report/run/list）。
- 核验器：`file_exists` / `file_contains` / `journal_event` / `manual` / `shell`（默认关闭，`~/.hermes/zhulong/config.json` 的 `allow_shell_verifiers: true` 开启）。
- 结算规则：**真 → 立即结算；假 → 等 `deadline_seconds`（默认 3600s）后结算**；agent 永远不能结算自己的预测（只有机械核验器与人工 `/zhulong calibrate resolve`）。
- 指标：Brier、ECE（5 档）、命中率、弃答计数；每日快照写入 `calib_metrics`。
- 测试：`tests/` 共 8 项（存储 3 + 校准 5），`python3 -m unittest discover -s tests`。

## 8. v0.3.0 实现注记（S4）

- 反思：确定性 digest（事件/工具/错误/校准统计）→ `reflections/`；可选单次 `ctx.llm` 复盘（标注未经核验）→ PROPOSALS.md（只读提案，永不自动执行）。
- 探针：10 项电池（6 知识 + 2 未知 + 1 假前提 + 1 定性），机械判分；每周一（`probe_weekday`/`probe_hour` 可配）自动 + `/zhulong probes run` 手动。
- 预算：`llm_daily_cap`（默认 40/日）共享计数（`llm_daily` 表），超限跳过。
- 调度：插件后台线程（30min 间隔）；跨进程任务认领（`tasks` 表，失败最多重试 5 次）；随 `scheduler: false` 或 `ZHULONG_NO_AUTOSWEEP=1` 关闭。
- 工具：`zhulong_calibration` 动作扩展：reflect / probes / run_probes。
- 测试：`tests/` 共 13 项。
