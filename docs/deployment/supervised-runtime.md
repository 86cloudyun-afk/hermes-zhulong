# 受监督自主运行（v0.5）

这套入口把已实现的目标闭环放进可启动、观察和停止的运行环境：一个
stdlib 监督器启动一个原生 Hermes 网关，现有插件使用 `ctx.llm` 规划，通过
原生 Runs 接口执行。监督器不另建认知循环。

需要 Linux、非 root 用户、有 Docker socket 权限、可用 cgroup 资源限制、
Hermes 官方 PM 管理的 Python（含 messaging/aiohttp），以及固定宿主提交
`73162b00eefde3794bed0afb53d84a19c0eed230`。云开发环境已具备这些条件；
其中 `zhulong-python` 是 PM Python 启动器，`hermes` 是对应原生启动器。

## 创建专用部署

准备独立授权工作目录和源事实 JSON。它必须与 Hermes、插件代码及控制目录
完全分开。源文件必须直接放在工作目录顶层，且是只有一个硬链接的普通文件；
不接受嵌套目录、符号链接、FIFO 或其他特殊文件。工作目录和源文件的设备/
inode 身份写入清单，运行中替换或改名会阻止新工作。可信资料生产者可更新
同一文件的内容；本版不支持原子替换源文件或输入挂载迁移。把 [自主配置示例](../../examples/autonomy-config.json) 的来源和
输出路径改为该目录；本部署只接受 `file_contains` / `json_equals`，拒绝在
宿主执行模型生成代码的 `argv` 验收。代码可在容器内执行测试；数据型验收
只证明约定文件/字段，不能据此证明代码普遍正确。

先拉取并固定镜像摘要。开发环境实测镜像如下，镜像包含 Bash 和 Python：

```bash
docker pull python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
zhulong-python scripts/runtime.py init \
  --root /absolute/private/zhulong-runtime \
  --work /absolute/authorized-work \
  --hermes-root /workspace/.cloud-onboarding/dependencies/hermes-agent \
  --hermes-command /workspace/.cloud-onboarding/bin/hermes \
  --autonomy-config /absolute/autonomy-config.json \
  --image python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
```

`--root` 必须是新目录。命令生成私有 profile、插件副本、配置及部署清单，
并生成仅用于本地 API 的强随机 `api.key`（0600）。API 固定 loopback；
模型密钥沿用保险库注入的 `DEEPSEEK_API_KEY`，不写入这些配置。默认模型为
`deepseek / deepseek-flash`。本地 API key 和模型 key 是不同凭据。

清单固定代码、宿主提交、配置和镜像。运行中配置/代码哈希变化会关闭服务，
防止静默放宽权限。更新前正常停止并保留旧 profile/账本、清单和 key；本版
没有自动升级或降级协议。不要删除未决提交，也不要以初始化新部署替代恢复。

## 检查、运行、观察、停止

```bash
zhulong-python scripts/runtime.py check --deployment /absolute/private/zhulong-runtime/deployment.json
zhulong-python scripts/runtime.py run --deployment /absolute/private/zhulong-runtime/deployment.json
# 在另一个终端中：
zhulong-python scripts/runtime.py status --deployment /absolute/private/zhulong-runtime/deployment.json
zhulong-python scripts/runtime.py stop --deployment /absolute/private/zhulong-runtime/deployment.json
```

`check` 不调用外部模型：构造实际原生 agent，确认最终模型工具只有
`terminal` / `process_manage`，再通过原生终端后端创建和检查容器。未知
工具、额外挂载、初始化失败或权限/资源漂移都会阻止新工作。
检查和运行使用同一个部署锁；预检失败、超时或取消也会清理自己创建的进程
组及部署标签容器。锁被另一实例占用时直接拒绝，保留该实例的资源。

`run` 是前台进程。它取得锁，完成检查后启动原生网关；同时要求认证的
readiness JSON、durable Runs 能力和本次 boot 的插件进度。HTTP 200 或
`/health` 响应不能单独证明就绪，也不证明模型凭据/提供商连接已验证。
控制记录仍为 starting 时不规划、不派发新目标。running 后按任务预算工作。

`status` 返回服务与插件的 JSON：包括 phase、ticks、错误类型代码、暂停状态
及占用计数。它核对 Linux 进程启动身份、本次 boot 和健康记录时效；孤儿、
过期或异常状态分别标为 `orphaned` / `stale` / `unhealthy`，历史状态保留为
`reported_state`，插件记录标明 `current`。状态查询及停止只依赖控制清单，
工作路径丢失、输出链接变化或自主配置损坏不会阻止这两个命令。
健康文件不保存聊天、模型响应或密钥。原生 `gateway.log` 可能
含原生输出，留在 0700 控制目录，不用于公开报告。

`stop` 写入独立于 boot 生命周期的持久请求，预检和失败重启不会覆盖它；
请求到达后不继续启动新网关。以后显式执行 `run` 开始新的监督调用，不自动
重置启动预算。命令返回时服务可能仍在收尾。监督器先关闭新规划/
派发，等待本次 boot 的停止确认，再让原生网关排空；到期限后强制结束自己
的进程组，包含已经退出的组长留下的成员，清理自己 `zhulong.runtime` 标签的容器。
清理失败会保留错误并报告 blocked。状态中的
`admission_acknowledged`、`forced_shutdown` 和 `removed_workers` 分别记录
这些事实。监督器不据此把未知任务改成已结算。

## 权限与恢复边界

| 项目 | 实际约束 |
|---|---|
| 模型工具 | 原生最终 schema 检查；关闭 Tool Search 桥、MCP 及额外用户插件工具 |
| 文件 | 仅授权工作 rw；顶层普通单链接源事实 ro；命名的本 profile 运行缓存 ro、skills 仅空目录 |
| 控制数据 | profile 配置、SQLite、API key、代码和 Docker socket 不进入工作容器 |
| 执行 | 非 root UID、只读根、no-new-privileges、有效 capabilities 为零 |
| 网络 | Docker network none；容器内 loopback 无法访问宿主 API |
| 资源 | 实际 inspect 1 CPU、512 MiB 内存及内存+swap 总额、128 PID、64 MiB shm；逐项检查固定 tmpfs 路径/选项/大小 |
| 磁盘 | 当前 vfs 驱动不能为 bind 工作卷强制磁盘配额；宿主配额需另行配置 |
| 重启 | 启动次数持久化；默认整个部署最多 6 次启动，耗尽则 blocked，不无限重启 |
| 重复实例 | flock 继承给网关；监督器死亡后活着的网关继续阻止另一个实例 |
| 不确定执行 | 原 submission/请求/身份和占用保留；重启不会退款、重编号或盲目重做 |

Docker daemon、原生宿主和插件 Python 属于可信控制面；Docker 组权限具有
很高的宿主权限。这里隔离的是模型工具动作，不是恶意可信插件或其他同用户
宿主程序。缓存只来自此专用 profile，不能加入其他 profile、技能、凭据或
共享宿主缓存。不要绕开检查自行扩大工具或挂载。

普通进程退出不会调用原生插件 unload；本版为此增加私有停止协议。运行状态
写入原子私有文件，规划次数只计完成的规划，崩溃不消耗空租约。已验证结果
保持不变，后续跟踪失败单独记录且不会释放未知占用。

## 在真正的 Linux 主机常驻

仓库提供 [systemd 示例](../../examples/zhulong-runtime.service)。替换其中路径、
用户和官方 PM Python 后再安装。提供商环境文件由部署者从保险库提供，
权限设为 0600；示例不含密钥。`KillMode=control-group` 在监督器死亡后清理
所属进程，Docker workers 由下一次监督器按部署标签检查/清理；继承的锁
在孤儿网关仍存活时阻止新启动。

监督器自身/机器死亡需要外层进程管理器和保留卷，这与子网关崩溃不同。
Codex 云任务的 PID 1 不是 systemd，环境快照也不保留运行进程。因此本次
交付可执行部署入口和有限验证，不声称已在另一台服务器安装常驻服务。

## 可复现的有限验证

```bash
HERMES_AGENT_ROOT=/path/to/pinned/hermes-agent zhulong-python -m unittest discover -s tests -v
zhulong-python scripts/host_smoke.py --hermes-root /path/to/pinned/hermes-agent
# 默认只检验真实原生/Docker 启停；--paid 才触发一个实际模型目标。
zhulong-python scripts/supervised_runtime_smoke.py \
  --hermes-root /path/to/pinned/hermes-agent \
  --hermes-command /path/to/native/hermes \
  --image python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 \
  --report /tmp/zhulong-runtime-report.json
```

离线进程测试独立统计接纳和副作用：丢回复后跨进程重放仍是两个请求、一次
接纳、一次副作用、一个尝试和一个真值。其他测试覆盖连续源认领崩溃、错误
boot、崩溃重启和持久耗尽、孤儿锁、非协作停止、配置漂移及停止顺序。
这些是有限故障场景，不是 24 小时 soak 或全年可用率证明。
