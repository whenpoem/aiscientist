"""Small translation table for the cockpit TUI."""

from __future__ import annotations

SUPPORTED_LANGS = {"en", "zh"}
DEFAULT_LANG = "en"

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "app_name": "research-cockpit",
        "tree_title": "1 Hypothesis Tree",
        "detail_title": "2 Node Detail",
        "events_title": "3 Event Stream",
        "tabs_title": "4 {active}",
        "tabs_title_all": "4 Risks / Failures / Claims / Literature",
        "filter_suffix": "filter: {value}",
        "no_hypotheses": "No hypotheses yet. Trigger a research session in Claude Code.",
        "select_hint": "Select a hypothesis with j/k or click.",
        "no_events": "No cockpit events yet.",
        "risks": "Risks",
        "failures": "Failures",
        "claims": "Claims",
        "literature": "Literature",
        "severity": "severity",
        "category": "category",
        "item": "item",
        "summary": "summary",
        "failure_id": "#",
        "trigger": "trigger",
        "symptom": "symptom",
        "seen": "seen",
        "metric": "metric",
        "value": "value",
        "dataset": "dataset",
        "verified": "verified",
        "seeds": "seeds",
        "paper_id": "paper_id",
        "title": "title",
        "year": "year",
        "task": "task",
        "score": "score",
        "no_risks": "No active risks.",
        "no_failures": "No failures yet.",
        "no_claims": "No claims yet.",
        "no_literature": "No literature yet.",
        "yes": "yes",
        "no": "no",
        "status": "Status",
        "kind": "Kind",
        "elo": "Elo",
        "evidence": "Evidence",
        "parents": "Parents",
        "children": "Children",
        "cross_edges": "Cross-edges",
        "created": "Created",
        "created_by": "Created by",
        "next_action": "Next action",
        "next_refuted": "Keep archived unless new evidence appears.",
        "next_evidence": "Review the linked hypothesis and update its claim if needed.",
        "next_hypothesis": "Approve, reject, redirect, constrain, or pin a metric.",
        "node_text": "Text",
        "supports": "supports",
        "refutes": "refutes",
        "support_refute": "{supports} supports / {refutes} refutes",
        "hud": (
            "{app}  active H {active_hypotheses} / refuted {refuted_nodes} / "
            "claims {pinned_claims} ({unverified_claims} unverified) / "
            "heldout {heldout} / risks {risks} / last {last_event}  {clock}"
        ),
        "heldout_none": "none",
        "last_never": "never",
        "just_now": "now",
        "seconds_ago": "{value}s ago",
        "minutes_ago": "{value}m ago",
        "hours_ago": "{value}h ago",
        "context_tree": "Tree: j/k move · y/n approve/reject · p pin · L language",
        "context_tabs": "Tabs: f cycle · Enter detail · / filter · L language",
        "context_events": "Events: t time · Ctrl-L clear · / filter · L language",
        "context_detail": "Detail: Tab change pane · Esc close detail · L language",
        "help_navigation": "Navigation",
        "help_title": "Help",
        "help_close": "Press any key to close.",
        "confirm_hint": "Press y to confirm, n or Esc to cancel.",
        "pin_title": "Pin metric",
        "pin_dataset": "dataset",
        "pin_metric_field": "metric",
        "pin_value": "value",
        "pin_help": "Tab moves between fields. Enter on value submits.",
        "help_actions": "Actions",
        "help_meta": "Meta",
        "move_selection": "move selection",
        "collapse_expand": "collapse/expand or move focus",
        "jump_pane": "jump to pane",
        "cycle_panes": "cycle panes",
        "approve_reject": "approve or reject",
        "redirect_constrain": "redirect or constrain",
        "mark_refuted": "mark refuted",
        "pin_metric": "pin metric",
        "halt_agent": "halt agent",
        "filter": "filter",
        "command_mode": "command mode",
        "toggle_time": "toggle timestamps",
        "toggle_refuted": "toggle refuted",
        "toggle_language": "toggle language",
        "quit": "quit",
        "command_placeholder": "Enter command, e.g. note remember baseline",
        "filter_tree": "Filter hypothesis tree",
        "filter_events": "Filter event stream",
        "filter_tabs": "Filter active right tab",
        "redirect_title": "Redirect hypothesis",
        "redirect_prompt": "Enter redirect text",
        "constrain_title": "Constrain hypothesis",
        "constrain_prompt": "Enter constraint text",
        "mark_refuted_title": "Mark Refuted",
        "mark_refuted_prompt": "Mark {node_id} as refuted?",
        "halt_title": "Halt Agent",
        "halt_prompt": "Queue a halt intervention?",
        "no_node": "No node selected.",
        "language_notice": "Language: English",
        "risk_claim": "claim",
        "risk_seed": "seed",
        "risk_failure": "failure",
        "risk_heldout": "held-out",
        "risk_contradiction": "contradiction",
        "risk_high": "high",
        "risk_medium": "medium",
        "risk_low": "low",
        # Proof trunk events (P5).
        "event_proof_corpus_ingested": "proof corpus ingested: {problem_id}",
        "event_proof_segmented": "proof segmented: draft {draft_id} ({snippet_count} snippets)",
        "event_proof_diagnosis_recorded": (
            "diagnosis recorded: snippet {snippet_id} flawed={is_flawed}"
        ),
        "event_proof_diagnosis_complete": (
            "diagnosis complete: manifest {manifest_id} -> {status} "
            "({flawed_count}/{entry_count} flawed)"
        ),
        "event_proof_correction_applied": (
            "proof correction applied: draft {old_draft_id} -> {new_draft_id}"
        ),
        "event_lean_proof_succeeded": (
            "Lean verified: proposition {proposition_id} (attempt {attempt_id})"
        ),
        "event_lean_proof_failed": (
            "Lean failed: proposition {proposition_id} (attempt {attempt_id})"
        ),
        "event_lean_proof_recorded": (
            "Lean attempt recorded: proposition {proposition_id} status {status}"
        ),
    },
    "zh": {
        "app_name": "研究座舱",
        "tree_title": "1 假设树",
        "detail_title": "2 节点详情",
        "events_title": "3 事件流",
        "tabs_title": "4 {active}",
        "tabs_title_all": "4 风险 / 失败 / 指标 / 文献",
        "filter_suffix": "过滤: {value}",
        "no_hypotheses": "还没有假设。请先在 Claude Code 中启动研究任务。",
        "select_hint": "用 j/k 或鼠标选择一个假设。",
        "no_events": "还没有 cockpit 事件。",
        "risks": "风险",
        "failures": "失败",
        "claims": "指标",
        "literature": "文献",
        "severity": "级别",
        "category": "类型",
        "item": "对象",
        "summary": "摘要",
        "failure_id": "#",
        "trigger": "触发",
        "symptom": "表现",
        "seen": "次数",
        "metric": "指标",
        "value": "数值",
        "dataset": "数据集",
        "verified": "已验证",
        "seeds": "种子",
        "paper_id": "文献ID",
        "title": "标题",
        "year": "年份",
        "task": "任务",
        "score": "分数",
        "no_risks": "当前没有活动风险。",
        "no_failures": "还没有失败记录。",
        "no_claims": "还没有固定指标。",
        "no_literature": "还没有文献记录。",
        "yes": "是",
        "no": "否",
        "status": "状态",
        "kind": "类型",
        "elo": "Elo",
        "evidence": "证据",
        "parents": "父节点",
        "children": "子节点",
        "cross_edges": "交叉边",
        "created": "创建时间",
        "created_by": "创建者",
        "next_action": "下一步",
        "next_refuted": "保持归档，除非出现新证据。",
        "next_evidence": "检查关联假设，必要时更新指标或结论。",
        "next_hypothesis": "批准、拒绝、重定向、约束，或固定一个指标。",
        "node_text": "正文",
        "supports": "支持",
        "refutes": "反驳",
        "support_refute": "{supports} 支持 / {refutes} 反驳",
        "hud": (
            "{app}  活跃假设 {active_hypotheses} / 已反驳 {refuted_nodes} / "
            "指标 {pinned_claims}（未验证 {unverified_claims}）/ "
            "留出集 {heldout} / 风险 {risks} / 最近 {last_event}  {clock}"
        ),
        "heldout_none": "无",
        "last_never": "无",
        "just_now": "刚刚",
        "seconds_ago": "{value} 秒前",
        "minutes_ago": "{value} 分钟前",
        "hours_ago": "{value} 小时前",
        "context_tree": "假设树: j/k 移动 · y/n 批准/拒绝 · p 固定指标 · L 切换语言",
        "context_tabs": "表格: f 切换 · Enter 详情 · / 过滤 · L 切换语言",
        "context_events": "事件: t 时间格式 · Ctrl-L 清空显示 · / 过滤 · L 切换语言",
        "context_detail": "详情: Tab 切换面板 · Esc 关闭详情 · L 切换语言",
        "help_navigation": "导航",
        "help_title": "帮助",
        "help_close": "按任意键关闭。",
        "confirm_hint": "按 y 确认，按 n 或 Esc 取消。",
        "pin_title": "固定指标",
        "pin_dataset": "数据集",
        "pin_metric_field": "指标",
        "pin_value": "数值",
        "pin_help": "Tab 切换字段，在数值框按 Enter 提交。",
        "help_actions": "操作",
        "help_meta": "其他",
        "move_selection": "移动选择",
        "collapse_expand": "折叠/展开，或移动焦点",
        "jump_pane": "跳到面板",
        "cycle_panes": "切换面板",
        "approve_reject": "批准或拒绝",
        "redirect_constrain": "重定向或添加约束",
        "mark_refuted": "标记为已反驳",
        "pin_metric": "固定指标",
        "halt_agent": "暂停 agent",
        "filter": "过滤",
        "command_mode": "命令模式",
        "toggle_time": "切换时间显示",
        "toggle_refuted": "显示/隐藏已反驳",
        "toggle_language": "切换语言",
        "quit": "退出",
        "command_placeholder": "输入命令，例如 note remember baseline",
        "filter_tree": "过滤假设树",
        "filter_events": "过滤事件流",
        "filter_tabs": "过滤当前表格",
        "redirect_title": "重定向假设",
        "redirect_prompt": "输入重定向说明",
        "constrain_title": "约束假设",
        "constrain_prompt": "输入约束条件",
        "mark_refuted_title": "标记为已反驳",
        "mark_refuted_prompt": "将 {node_id} 标记为已反驳？",
        "halt_title": "暂停 Agent",
        "halt_prompt": "加入暂停 intervention？",
        "no_node": "没有选中的节点。",
        "language_notice": "语言：中文",
        "risk_claim": "指标",
        "risk_seed": "种子",
        "risk_failure": "失败",
        "risk_heldout": "留出集",
        "risk_contradiction": "矛盾",
        "risk_high": "高",
        "risk_medium": "中",
        "risk_low": "低",
        # 证明主干事件 (P5)
        "event_proof_corpus_ingested": "证明语料入库: {problem_id}",
        "event_proof_segmented": "证明已切片: 草稿 {draft_id}（{snippet_count} 个片段）",
        "event_proof_diagnosis_recorded": (
            "诊断已记录: 片段 {snippet_id} 是否有瑕疵={is_flawed}"
        ),
        "event_proof_diagnosis_complete": (
            "诊断完成: 清单 {manifest_id} -> {status}"
            "（{flawed_count}/{entry_count} 处瑕疵）"
        ),
        "event_proof_correction_applied": (
            "证明已修正: 草稿 {old_draft_id} -> {new_draft_id}"
        ),
        "event_lean_proof_succeeded": (
            "Lean 验证通过: 命题 {proposition_id}（尝试 {attempt_id}）"
        ),
        "event_lean_proof_failed": (
            "Lean 验证失败: 命题 {proposition_id}（尝试 {attempt_id}）"
        ),
        "event_lean_proof_recorded": (
            "Lean 尝试已记录: 命题 {proposition_id} 状态 {status}"
        ),
    },
}


def normalize_lang(lang: str | None) -> str:
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def toggle_lang(lang: str) -> str:
    return "zh" if normalize_lang(lang) == "en" else "en"


def t(lang: str, key: str, **kwargs: object) -> str:
    normalized = normalize_lang(lang)
    template = TEXT.get(normalized, {}).get(key, TEXT[DEFAULT_LANG].get(key, key))
    return template.format(**kwargs) if kwargs else template


def state_label(lang: str, state: str) -> str:
    labels = {
        "en": {
            "active": "active",
            "refuted": "refuted",
            "superseded": "superseded",
            "archived": "archived",
        },
        "zh": {
            "active": "活跃",
            "refuted": "已反驳",
            "superseded": "已替代",
            "archived": "已归档",
        },
    }
    return labels[normalize_lang(lang)].get(state, state)


def kind_label(lang: str, kind: str) -> str:
    labels = {
        "en": {
            "question": "question",
            "hypothesis": "hypothesis",
            "experiment": "experiment",
            "evidence": "evidence",
            "conclusion": "conclusion",
            "proposition": "proposition",
            "proof_skeleton": "proof skeleton",
            "proof_snippet": "proof snippet",
        },
        "zh": {
            "question": "问题",
            "hypothesis": "假设",
            "experiment": "实验",
            "evidence": "证据",
            "conclusion": "结论",
            "proposition": "命题",
            "proof_skeleton": "证明骨架",
            "proof_snippet": "证明片段",
        },
    }
    return labels[normalize_lang(lang)].get(kind, kind)


# Trunk-aware icons for tree pane rendering (architecture.md §13).
# Empirical kinds get the gear glyph; proof kinds get the triangle.
KIND_ICONS = {
    "question": "?",
    "hypothesis": "*",
    "experiment": "x",
    "evidence": ".",
    "conclusion": "!",
    "proposition": "T",
    "proof_skeleton": "S",
    "proof_snippet": "s",
}


def kind_icon(kind: str) -> str:
    return KIND_ICONS.get(kind, "-")
