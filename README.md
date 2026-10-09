# 烛龙 Zhulong 🐉

**开眼即观测。** Hermes Agent 的自我观测层（self-observation spine）—— 把 agent 的行为流（工具、回合、会话、技能、委派、错误、命令）落成一本可对账的日记。

> 「钟山之神，名曰烛阴……其瞑乃晦，其视乃明。」——《山海经·大荒北经》

## 这是什么

Zhulong 是 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的插件，只做一件事：**观察**。它订阅 Hermes 的 observer hooks，把每个生命周期事件规范化、脱敏、写入本地日记（JSONL + SQLite）。这是「自我觉醒」工程阶梯的第一级（A1 自感知）——一切高级能力（自模型、自校准、自叙事）都建立在这本日记之上。

## 原则（写死，不妥协）

- **仅观测**：不修改对话、不改 system prompt、零 LLM 调用（v0.1 完全免费）。
- **失败开放**：任何回调异常都吞掉，绝不阻塞或影响主循环。
- **隐私优先**：只存元数据（名称/状态/大小/字段名），**不存**工具参数原文、结果原文、消息正文、prompt。
- **缓存安全**：不进 system prompt（v0.1 无任何提示注入）。
- **数据本地**：全部落在 `$HERMES_HOME/zhulong/`，可用 `ZHULONG_RETENTION_DAYS`（默认 90 天）控制留存。

## 安装

```bash
bash scripts/install.sh          # 复制到 ~/.hermes/plugins/zhulong
hermes plugins enable zhulong    # 加入 allow-list
```

重启 Hermes（网关/CLI 任一面）后生效。

## 使用

```
/zhulong status     # 今日/累计统计
/zhulong tail 30    # 最近 30 条事件
/zhulong help
```

## 观测的事件（v0.1）

`post_tool_call` · `post_llm_call` · `on_session_start/end/finalize/reset` · `on_skill_lifecycle` · `subagent_stop` · `api_request_error` · `agent_loop_stopped` · `pre_command`

## 数据布局

```
~/.hermes/zhulong/
├── journal/events-YYYY-MM-DD.jsonl   # 真源（append-only）
└── zhulong.db                        # SQLite 索引（查询用）
```

## 路线图

- ✅ v0.1.0（S2 MVP）：观测脊柱（本版）
- ⏳ S3：校准账（预测-结果对账、Brier/ECE）
- ⏳ S4：反思引擎 + 自省探针（自动，预算受控）
- ⏳ S5：`/zhulong model` 自我模型 + 仪表盘

## License

MIT © 2026 YG
