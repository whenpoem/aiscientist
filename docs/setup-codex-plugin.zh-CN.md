# Codex 插件安装

公开插件是 Codex CLI 与 Codex 桌面端的可移植安装方式。v5.1.2 插件
定义打包四个默认启用的本地 MCP、两个默认关闭的文献 MCP 定义、七个 Skills、hooks
和 Cockpit 接入；研究状态仍保存在当前项目中。

## 安装

```powershell
uv tool run --from claudescientist==5.1.2 claudescientist setup --scope user
```

等价的手动命令是：

```powershell
codex plugin marketplace add whenpoem/aiscientist --ref v5.1.2
codex plugin add claudescientist@claudescientist
```

公开安装依赖两个版本一致的发布物：运行本地 MCP 与 hooks 的
`claudescientist==5.1.2` Python 包，以及分发插件的 `v5.1.2` Git 标签。新用户安装
之前，两者都必须已经发布。源码开发时可以通过 `--marketplace-source` 传入本地
marketplace 路径；setup 会为本地路径自动省略只适用于 Git 的 `--ref` 参数。

安装后新建 Codex 任务。Codex 弹出插件 hooks 信任提示时，检查后批准，才能启用
Cockpit 干预交付和生命周期保护。

## 在任意项目中检查

```powershell
uv tool run --from claudescientist==5.1.2 claudescientist doctor --workspace .
```

Doctor 会分别报告插件状态、核心模块、工作区与数据库路径、Cockpit 监控、hooks
信任和干预交付。hooks 未信任时会明确降级为 `monitor-only`：事件仍能显示，但
排队的干预不能进入下一轮 Codex。

## 打开 Cockpit

```powershell
uv tool run --from claudescientist==5.1.2 claudescientist cockpit --workspace .
uv tool run --from claudescientist==5.1.2 claudescientist cockpit --workspace . --lang zh
```

插件与 Cockpit 会解析到同一个工作区数据库。公开安装插件不会公开研究数据，也
不会启动 Web 服务。

## 可选文献集成

插件默认只启用 `memory`、`verify`、`prove`、`cockpit`。v5.1.2 同时提供已固定
版本、默认关闭的 `arxiv` 和 `openalex` MCP。可以在 **设置 > MCP 服务器** 中开启
其中任意一个，然后新建 Codex 任务。等价的 `~/.codex/config.toml` 用户配置是：

```toml
[plugins."claudescientist@claudescientist".mcp_servers.arxiv]
enabled = true

[plugins."claudescientist@claudescientist".mcp_servers.openalex]
enabled = true
```

arXiv 需要 `uv`，首次使用会下载 `arxiv-mcp-server==0.5.0`。OpenAlex 需要
Node.js/npm，并通过 `npx` 启动 `openalex-research-mcp@0.5.0`。如果缺少对应启动器，
应保持该服务器关闭。Doctor 会同时读取项目级 MCP 和这些插件开关来报告就绪状态。

Lean 仍需要按 [setup-lean.zh-CN.md](setup-lean.zh-CN.md) 单独安装工具链。外部 MCP
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
