# Codex 安装与使用

> English version: [setup-codex-plugin.md](setup-codex-plugin.md)

本文面向公开 Codex 插件的普通用户。源码贡献者使用另一套开发命令，见本文后面的“源码贡献者”。

ClaudeScientist 包含两个安装部分：

- Python 包提供 `claudescientist` 命令、MCP 后端、Doctor、Cockpit 和项目配置命令。
- Codex 插件提供 Skills、hooks 和 MCP 启动定义。

每个研究项目的配置和状态都保存在该项目的 `.research-agent/` 下。安装目录不保存研究数据。

## 1. 安装 Python 包和插件

先安装 [uv](https://docs.astral.sh/uv/) 和 Codex，并确认两个命令可用：

```powershell
uv --version
codex --version
```

然后运行：

```powershell
uv tool install claudescientist==5.1.4
claudescientist setup --scope user
```

第一条命令为当前系统用户安装 CLI。第二条命令从对应的 Git 标签安装公开 Codex 插件。这两条命令每台电脑运行一次，不需要在每个研究项目中重复运行。

检查版本：

```powershell
claudescientist --version
```

正常输出为：

```text
claudescientist 5.1.4
```

也可以手动安装插件：

```powershell
codex plugin marketplace add whenpoem/aiscientist --ref v5.1.4
codex plugin add claudescientist@claudescientist
```

手动安装插件不会安装 `claudescientist` CLI，因此普通用户仍建议使用前面的两条安装命令。

## 2. 为每个研究项目配置一次

进入准备使用 Codex 的研究项目，然后运行：

```powershell
cd D:\你的研究项目
claudescientist configure --workspace .
```

这个命令会创建：

```text
.research-agent/config.toml
```

交互式配置包含以下内容：

1. 证明语料检索使用的 embedding 后端和模型。
2. held-out 隔离数据目录。
3. 是否允许系统自动暂停低强度分支。
4. 当前项目是否使用 Lean，以及 mathlib 项目路径。

配置文件只保存非敏感设置，不要把 API Key 写进去。使用 OpenAI 兼容的 embedding 服务时，应当在启动 Codex 前，通过终端或操作系统环境变量设置 `OPENAI_API_KEY`。

这个命令可以重复运行，已有配置会作为默认值。自动化环境可以使用非交互参数，例如：

```powershell
claudescientist configure --workspace . --non-interactive `
  --embedding-backend mock `
  --heldout-dir D:\research-heldout `
  --no-auto-prune `
  --no-lean
```

显式设置的环境变量优先于项目配置文件，因此临时调整某项设置时不必修改 `config.toml`。

## 3. 启动 Codex、Doctor 和 Cockpit

安装或修改配置后，从研究项目中新建 Codex 任务，让 Codex 重新读取插件、MCP 和 hooks：

```powershell
codex -C .
```

使用桌面版时，把同一个项目目录作为任务工作区打开。

如果 Codex 询问是否信任插件 hooks，请先查看内容，再根据需要允许。未信任 hooks 时，MCP 监控仍可使用，但 Cockpit 的人工干预只能停留在 `monitor-only` 状态，不能送入下一轮 Codex 任务。

在项目目录中检查配置：

```powershell
claudescientist doctor --workspace .
```

Doctor 会检查工作区、项目配置、数据库位置、插件状态、hook 信任状态、可选 MCP、embedding 后端和 Lean 是否就绪。

在第二个终端打开 Cockpit：

```powershell
claudescientist cockpit --workspace . --lang zh
```

Codex 和 Cockpit 必须使用同一个工作区。这样它们会共同读写 `.research-agent/state.db`。Cockpit 是本地终端程序，不会上传数据库。

在 Codex 中启动完整研究流程：

```text
$research-sop 研究所提出的方法是否优于基线
```

也可以输入 `/skills`，再选择具体 Skill。

## 4. 各项设置在哪里完成

| 设置 | 配置位置 | 生效范围 |
|---|---|---|
| 安装插件 | `claudescientist setup --scope user` | 当前系统用户 |
| embedding、held-out、自动剪枝、Lean 项目 | `claudescientist configure --workspace .` | 当前研究项目 |
| arXiv、OpenAlex、Lean MCP 是否启用 | Codex 的插件或 MCP 设置 | 当前 Codex 用户 |
| API Key | 终端或操作系统环境变量 | 当前进程或当前用户 |
| 研究记录 | `.research-agent/state.db` | 当前研究项目 |
| Cockpit 语言和主题 | Cockpit 启动参数 | 本次启动 |

ClaudeScientist 会在启动核心 MCP、hook、Doctor 或 Cockpit 前自动读取项目配置，不需要用户手动加载 `.env`。

## 5. 可选 MCP

公开插件默认启用四个本地 MCP，同时带有三个默认关闭的可选 MCP：

| MCP | 默认状态 | 用途 |
|---|---|---|
| `memory` | 开启 | 研究图、证据、比较、失败记录和文献记录 |
| `verify` | 开启 | 溯源、随机种子检查、预注册、held-out 查询和预算 |
| `prove` | 开启 | 自然语言证明流程和证明记录 |
| `cockpit` | 开启 | 事件、监控和人工干预 |
| `arxiv` | 关闭 | 搜索和获取 arXiv 论文 |
| `openalex` | 关闭 | 搜索和获取 OpenAlex 文献记录 |
| `lean` | 关闭 | 可选的 Lean 机器验证 |

### arXiv

打开 Codex 设置，找到 ClaudeScientist 插件的 MCP，启用 `arxiv`，然后新建任务。第一次启动时，`uv` 会下载 `arxiv-mcp-server==0.5.0`。

等价的用户配置为：

```toml
[plugins."claudescientist@claudescientist".mcp_servers.arxiv]
enabled = true
```

### OpenAlex

OpenAlex 需要 Node.js 和 npm。先检查：

```powershell
npx --version
```

然后在 ClaudeScientist 插件的 MCP 设置中启用 `openalex`，并新建任务。如果系统中没有 `npx`，保持关闭即可。

等价的用户配置为：

```toml
[plugins."claudescientist@claudescientist".mcp_servers.openalex]
enabled = true
```

### Lean

自然语言证明的起草和检查不依赖 Lean。需要机器验证时，按以下步骤配置：

1. 按照 [Lean 安装指南](setup-lean.zh-CN.md)安装 `elan`、Lean、`lake`、`lean-lsp-mcp`，并创建 mathlib 项目。
2. 再次配置当前工作区：

   ```powershell
   claudescientist configure --workspace . --lean `
     --lean-project .research-agent\lean\claudescientist-proofs
   ```

3. 在 Codex 的 ClaudeScientist 插件 MCP 设置中启用 `lean`。
4. 新建 Codex 任务，再运行 `claudescientist doctor --workspace .`。

插件通过 ClaudeScientist CLI 启动 Lean，CLI 会读取当前工作区中保存的 mathlib 路径。因此，不同研究项目可以使用各自的 Lean 项目，不需要反复替换一个全局 MCP 启动命令。

如果当前项目不再使用 Lean，重新运行配置命令并加上 `--no-lean`。也可以在 Codex 设置中全局关闭 Lean MCP。

## 6. held-out 数据

配置命令会设置隔离数据的保存目录。注册数据集时运行：

```powershell
uv tool run --from claudescientist==5.1.4 python -m claudescientist.heldout `
  register <名称> <路径>
```

注册操作会把原始数据移动到 held-out 目录，不会另外复制一份。重要数据应当先备份。注册后，代理应通过 `query_heldout` 验证工具访问，而不是直接读取文件。

## 7. 源码贡献者

旧的项目设置向导现在通过下面的命令运行：

```powershell
git clone https://github.com/whenpoem/aiscientist.git
cd aiscientist
uv sync
uv run claudescientist dev-setup
```

这个向导只用于开发 ClaudeScientist 源码仓库。它会检查开发工具、生成项目级 Claude Code/Codex 适配文件、写入源码仓库的 `.env`、安装可选证明依赖，并可以导入仓库自带的证明语料。

`claudescientist setup --scope project` 暂时保留为兼容入口。运行时会显示弃用提示，然后转到 `dev-setup`。普通插件用户不要在研究项目中运行这两个命令。

## 8. 更新与卸载

更新 Python 包后，删除旧的固定版本插件来源，再安装对应的新插件：

```powershell
uv tool upgrade claudescientist
codex plugin remove claudescientist
codex plugin marketplace remove claudescientist
claudescientist setup --scope user
```

已有的 `.research-agent/config.toml` 和 `.research-agent/state.db` 不会被删除。

卸载命令：

```powershell
codex plugin remove claudescientist
uv tool uninstall claudescientist
```

卸载程序也不会删除已有研究项目中的配置和数据。

## 9. 常见检查结果

- `workspace_configuration: degraded`：在研究项目中运行 `claudescientist configure --workspace .`。
- `monitor-only`：信任插件 hooks，然后新建 Codex 任务。
- arXiv 或 OpenAlex 关闭：正常，需要对应文献源时再开启。
- Lean 状态异常：检查工具链、`lakefile.lean`、项目配置和插件 MCP 开关。
- Cockpit 没有内容：检查 Codex 与 Cockpit 是否使用同一个工作区。
- 安装后看不到 Skills：新建 Codex 任务，让插件发现过程重新执行。
