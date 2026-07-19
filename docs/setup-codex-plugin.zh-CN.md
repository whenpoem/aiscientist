# Codex 安装与使用

> English version: [setup-codex-plugin.md](setup-codex-plugin.md)

本文面向公开 Codex 插件的普通用户，同时适用于 Codex CLI 和 Codex 桌面端。源码
贡献者还需要阅读[项目级设置向导](#项目级设置向导)。

ClaudeScientist 的安装分为两部分：

- Python 包提供 `claudescientist` 命令、四个本地 MCP 后端、Doctor 和 Cockpit。
- Codex 插件提供 Skills、hooks 和 MCP 配置。插件源码固定在与 Python 包版本一致的
  Git 标签上。

研究数据不保存在安装目录中。每个研究项目使用自己的
`.research-agent/state.db`。

## 1. 安装前准备

请先安装 `uv` 和 Codex，然后在 PowerShell 中检查：

```powershell
uv --version
codex --version
```

四个核心 MCP 不需要 Node.js。OpenAlex 是可选功能，需要 Node.js/npm。Lean 也是
可选功能，需要单独安装。

## 2. 推荐安装方式

下面两条命令只需要运行一次：

```powershell
uv tool install claudescientist==5.1.3
claudescientist setup --scope user
```

第一条命令为当前 Windows 用户永久安装 `claudescientist` 命令，同时安装 Cockpit、
Doctor 和本地 MCP 后端代码。

第二条命令让 Codex 添加固定在 GitHub `v5.1.3` 标签上的 ClaudeScientist
marketplace，并安装 `claudescientist@claudescientist` 插件。这个命令不是交互式
项目配置向导。

检查 Python 包版本：

```powershell
claudescientist --version
```

预期输出：

```text
claudescientist 5.1.3
```

### 不永久安装命令行工具

下面这条命令也能安装插件：

```powershell
uv tool run --from claudescientist==5.1.3 claudescientist setup --scope user
```

它适合不想永久保留 `claudescientist` 命令的用户。以后运行 Doctor 和 Cockpit 时，
也必须继续使用较长的 `uv tool run --from ...` 写法。

### 手动安装 Codex 插件

下面两条命令只安装 Codex 插件：

```powershell
codex plugin marketplace add whenpoem/aiscientist --ref v5.1.3
codex plugin add claudescientist@claudescientist
```

这种方式适合排查插件安装问题，但不会永久安装 `claudescientist` 命令。大多数用户
使用前面的推荐方式更方便。

## 3. 在研究项目中首次使用

在准备交给 Codex 的项目目录中打开 PowerShell。这个目录可以是已有项目，也可以是
空目录，不需要是 ClaudeScientist 源码仓库。

```powershell
cd D:\你的研究项目
claudescientist doctor --workspace .
```

Doctor 会显示实际使用的工作目录、数据库路径、插件状态、MCP 导入、Cockpit 监控、
hooks 信任状态和干预交付状态。首次建立受信任的 Codex 任务之前，hooks 信任警告是
正常现象。

从这个目录启动 Codex：

```powershell
codex -C .
```

如果使用 Codex 桌面端，请把同一个目录作为任务工作区。安装插件后要新建一个任务，
这样 Codex 才会重新读取插件和 MCP 配置。

Codex 第一次询问是否信任插件 hooks 时，请先检查再批准。批准后才能使用生命周期
检查和 Cockpit 干预交付。没有信任 hooks 时，MCP 事件仍能显示，但干预处于
`monitor-only` 状态，不能进入下一轮 Codex 对话。

在同一个项目中打开第二个 PowerShell：

```powershell
cd D:\你的研究项目
claudescientist cockpit --workspace . --lang zh
```

Codex 任务和 Cockpit 必须使用同一个工作目录。它们会读写同一个
`.research-agent/state.db`。Cockpit 不启动 Web 服务，也不会上传研究数据。

在 Codex 中输入下面的内容可以启动完整研究流程：

```text
$research-sop 研究新方法是否优于现有 baseline
```

也可以输入 `/skills`，再选择具体 Skill。Codex 使用 `$skill-name` 写法；
`/research-sop` 是 Claude Code 的写法。

## 4. 可选功能

公开插件默认启动四个本地 MCP：

| MCP | 默认状态 | 用途 |
|---|---|---|
| `memory` | 开启 | 研究图、证据、比较、失败记录和文献记录 |
| `verify` | 开启 | 溯源、随机种子检查、预注册、held-out 访问和预算 |
| `prove` | 开启 | 自然语言证明流程和证明记录 |
| `cockpit` | 开启 | 事件、监控和用户干预 |
| `arxiv` | 关闭 | 搜索和获取 arXiv 论文 |
| `openalex` | 关闭 | 搜索和获取 OpenAlex 文献记录 |
| `lean` | 公开插件不自动注册 | 通过 `lean-lsp-mcp` 进行可选的形式化验证 |

### 开启 arXiv

在 Codex 中打开 **设置 > MCP 服务器**，开启 `arxiv`，然后新建任务。第一次启动
会通过 `uv` 下载 `arxiv-mcp-server==0.5.0`。

等价的插件配置是：

```toml
[plugins."claudescientist@claudescientist".mcp_servers.arxiv]
enabled = true
```

### 开启 OpenAlex

先检查 Node.js/npm：

```powershell
npx --version
```

然后在 **设置 > MCP 服务器** 中开启 `openalex`，再新建任务。插件会通过 `npx`
启动 `openalex-research-mcp@0.5.0`。如果系统中没有 `npx`，请保持关闭。

等价的插件配置是：

```toml
[plugins."claudescientist@claudescientist".mcp_servers.openalex]
enabled = true
```

### 普通插件用户开启 Lean

不安装 Lean 也可以使用自然语言证明流程。只有需要 Lean 4 机器验证时才需要开启。
公开插件不会自动注册这个第三方 MCP，因为 Lean、mathlib 和项目缓存需要另外安装，
总占用通常达到数 GB。

请按下面的顺序操作：

1. 根据 [Lean 安装指南](setup-lean.zh-CN.md)安装 `elan`、Lean、`lake`，并建立
   mathlib 项目。
2. 在每个研究项目中把 mathlib 项目放在
   `.research-agent/lean/claudescientist-proofs`。
3. 从研究项目根目录注册 Lean MCP：

```powershell
codex mcp add lean -- uv tool run lean-lsp-mcp --lean-project-path .research-agent/lean/claudescientist-proofs
```

4. 从这个研究项目重新建立 Codex 任务，并确认 MCP 列表中出现 `lean`。

可以运行下面的命令检查，正常结果应显示 `lean` 为 `enabled`：

```powershell
codex mcp list
```

然后在新任务中测试：

```text
$prove-sop 证明实数加法满足交换律。如果命题符合条件，请使用 Lean 形式化验证。
```

上面的相对路径以当前研究项目为起点。如果 Lean 项目放在别处，请改成包含
`lakefile.lean` 的目录的完整路径。

较长的 Lean 运行应当先在验证预算中设置运行时间额度。Lean 安装指南提供了预算 MCP
调用和一个小型验证示例。

不再使用 Lean 时，运行 `codex mcp remove lean`，再新建 Codex 任务。这个命令不会
删除本地 mathlib 项目或已有证明记录。

## 5. 项目级设置向导

ClaudeScientist 有两个用途不同的 setup 命令：

| 命令 | 适用对象 | 修改内容 |
|---|---|---|
| `claudescientist setup --scope user` | 普通 Codex 插件用户 | 在用户的 Codex 配置中安装版本一致的 marketplace 和公开插件 |
| `claudescientist setup --scope project` | 源码贡献者，或者使用项目级 Claude Code/Codex 配置的开发者 | 运行旧的八步源码仓库向导，写入本地开发配置 |

项目级向导会检查当前目录是否存在 `pyproject.toml` 和 `.claude/`，因此它只适合在
ClaudeScientist 源码仓库中运行。它可以完成：

1. 检查 Python、`uv`、Claude Code、Codex 和 `npx`。
2. 选择 Claude Code、Codex 或同时使用两者。
3. 生成项目级 `.codex/config.toml`、agent 定义和 Skills。
4. 选择 embedding 后端并写入 `.env`。
5. 安装可选的证明依赖，并导入仓库自带的证明语料。
6. 设置 held-out 数据目录。
7. 检查 Lean 工具链是否已安装，但不会自动安装 Lean。
8. 设置自动暂停弱分支是仅给建议，还是实际启用。

只有开发本仓库，或者使用仓库自带的 Claude Code 配置时才运行：

```powershell
git clone https://github.com/whenpoem/aiscientist.git
cd aiscientist
uv sync
uv run python -m claudescientist.setup
```

普通插件用户不要在每个研究项目中运行这个向导。它会额外生成一套项目级 Codex
配置，使用户难以判断当前使用的是公开插件还是项目级生成文件。

## 6. 检查安装

在研究项目中运行：

```powershell
claudescientist doctor --workspace .
```

必要时再检查 Codex 插件和 MCP 列表：

```powershell
codex plugin list --json
codex mcp list
```

常见结果：

- `arxiv` 或 `openalex` 关闭：正常，只有需要对应文献源时才开启。
- Cockpit 显示 `monitor-only`：当前 Codex 任务尚未信任 hooks。
- Cockpit 没有内容：当前工作区还没有写入事件，或者 Codex 和 Cockpit 使用了不同
  的工作目录。
- 安装后看不到 Skill：新建一个 Codex 任务，让插件发现过程重新执行。

## 7. 更新

Marketplace 固定在具体发布标签上，因此普通的 marketplace refresh 只会刷新当前
版本，不会自动切换到新标签。升级到新的 ClaudeScientist 版本时，先升级 Python
命令，再移除旧插件来源并重新运行用户级 setup：

```powershell
uv tool upgrade claudescientist
codex plugin remove claudescientist
codex plugin marketplace remove claudescientist
claudescientist setup --scope user
```

这些命令不会删除研究数据库。更新后新建 Codex 任务，再运行一次 Doctor。用户级
setup 会读取新安装的 Python 版本，并选择对应的 Git 标签。

## 8. 卸载

```powershell
codex plugin remove claudescientist
uv tool uninstall claudescientist
```

卸载程序不会删除已有研究项目中的 `.research-agent/state.db` 或生成的报告。
