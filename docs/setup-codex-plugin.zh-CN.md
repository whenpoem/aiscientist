# Codex 插件安装

公开插件是 Codex CLI 与 Codex 桌面端的可移植安装方式。它打包四个本地 MCP、
七个 Skills、hooks 和 Cockpit 接入；研究状态仍保存在当前项目中。

## 安装

```powershell
uv tool run --from claudescientist==5.1.1 claudescientist setup --scope user
```

等价的手动命令是：

```powershell
codex plugin marketplace add whenpoem/aiscientist --ref v5.1.1
codex plugin add claudescientist@claudescientist
```

公开安装依赖两个版本一致的发布物：运行本地 MCP 与 hooks 的
`claudescientist==5.1.1` Python 包，以及分发插件的 `v5.1.1` Git 标签。新用户安装
之前，两者都必须已经发布。源码开发时可以通过 `--marketplace-source` 传入本地
marketplace 路径；setup 会为本地路径自动省略只适用于 Git 的 `--ref` 参数。

安装后新建 Codex 任务。Codex 弹出插件 hooks 信任提示时，检查后批准，才能启用
Cockpit 干预交付和生命周期保护。

## 在任意项目中检查

```powershell
uv tool run --from claudescientist==5.1.1 claudescientist doctor --workspace .
```

Doctor 会分别报告插件状态、核心模块、工作区与数据库路径、Cockpit 监控、hooks
信任和干预交付。hooks 未信任时会明确降级为 `monitor-only`：事件仍能显示，但
排队的干预不能进入下一轮 Codex。

## 打开 Cockpit

```powershell
uv tool run --from claudescientist==5.1.1 claudescientist cockpit --workspace .
uv tool run --from claudescientist==5.1.1 claudescientist cockpit --workspace . --lang zh
```

插件与 Cockpit 会解析到同一个工作区数据库。公开安装插件不会公开研究数据，也
不会启动 Web 服务。

## 可选集成

公开插件默认只启用 `memory`、`verify`、`prove`、`cockpit`：

```powershell
codex mcp add arxiv -- uv tool run arxiv-mcp-server==0.5.0
codex mcp add openalex -- npx -y openalex-research-mcp@0.5.0
```

Lean 需要按 [setup-lean.zh-CN.md](setup-lean.zh-CN.md) 安装工具链。外部 MCP
锁定版本，避免同一 ClaudeScientist 版本随时间静默改变行为。

## 项目本地兼容模式

贡献者仍可在源码仓库运行 `uv run python -m claudescientist.setup`，生成
`.codex/config.toml`、`.codex/agents/` 和 `.agents/skills/`。不要把这些生成文件
复制到每个研究仓库；跨项目使用应安装插件。

## 更新或移除

```powershell
codex plugin marketplace upgrade claudescientist
codex plugin remove claudescientist
```

更新后新建 Codex 任务并再次运行 doctor。移除插件不会删除任何项目已有的
`.research-agent/state.db`。
