"""Detail text builders for rows selected in cockpit tab panes."""

from __future__ import annotations

from typing import Any

from .i18n import t


def row_detail(row: dict[str, Any], lang: str) -> tuple[str, str]:
    """Return the detail-pane title/body for a selected tabular row."""
    if {"severity", "category", "summary"} <= set(row):
        return (
            f"{t(lang, 'risks')} {row['item']}",
            "\n".join(
                [
                    f"{t(lang, 'severity')}: {row['severity']}",
                    f"{t(lang, 'category')}: {row['category']}",
                    f"{t(lang, 'summary')}: {row['summary']}",
                ]
            ),
        )
    if "failure_id" in row:
        return (
            f"{t(lang, 'failures')} #{row['failure_id']}",
            "\n".join(
                [
                    f"{t(lang, 'trigger')}: {row['trigger']}",
                    f"{t(lang, 'symptom')}: {row['symptom']}",
                    f"{t(lang, 'failure_root_cause')}: {row.get('root_cause') or '-'}",
                    f"{t(lang, 'failure_resolution')}: {row.get('resolution') or '-'}",
                    f"{t(lang, 'seen')}: {row.get('seen_count', 0)}",
                    f"{t(lang, 'failure_signature')}: {row.get('signature') or '-'}",
                ]
            ),
        )
    if "problem_id" in row and "statement" in row:
        keywords = f"L{row.get('n_lexical', 0)} / S{row.get('n_semantic', 0)}"
        domain = ", ".join(row.get("domain_tags") or []) or "-"
        return (
            f"{t(lang, 'corpus_title')} {row['problem_id']}",
            "\n".join(
                [
                    f"{t(lang, 'corpus_col_domain')}: {domain}",
                    f"{t(lang, 'corpus_col_keywords')}: {keywords}",
                    f"{t(lang, 'created')}: {row.get('ingested_at', '-')}",
                    "",
                    f"{t(lang, 'corpus_col_statement')}:",
                    str(row.get("statement", "")),
                    "",
                    f"{t(lang, 'reference_proof')}:",
                    str(row.get("reference_proof", "")) or "-",
                ]
            ),
        )
    if "manifest_id" in row and "snippet_count" in row:
        status = str(row.get("status", "open"))
        status_label = t(lang, f"diagnostics_status_{status}")
        if status_label == f"diagnostics_status_{status}":
            status_label = status
        entries = row.get("entries") or []
        lines = [
            f"{t(lang, 'draft')}: {row.get('draft_id', '-')}",
            f"{t(lang, 'status')}: {status_label}",
            (
                f"{t(lang, 'diagnostics_col_snippets')}: "
                f"{row.get('snippet_count', 0)}  "
                f"{t(lang, 'diagnostics_col_flawed')}: "
                f"{row.get('flawed_count', 0)}"
            ),
            "",
        ]
        for entry in entries[:20]:
            if not isinstance(entry, dict):
                continue
            marker = "✗" if entry.get("is_flawed") else "✓"
            snippet_id = entry.get("snippet_id", "-")
            note = entry.get("note") or entry.get("rationale") or ""
            lines.append(f"  {marker} {snippet_id}  {note}".rstrip())
        return (
            f"{t(lang, 'diagnostics_title')} #{row['manifest_id']}",
            "\n".join(lines),
        )
    if "attempt_id" in row and "proposition_id" in row:
        status = str(row.get("status", "queued"))
        status_label = t(lang, f"lean_status_{status}")
        if status_label == f"lean_status_{status}":
            status_label = status
        duration = row.get("duration_sec")
        duration_text = (
            f"{float(duration):.2f}s"
            if isinstance(duration, (int, float))
            else "-"
        )
        reasons = ", ".join(row.get("triage_reasons") or []) or "-"
        lean_source = row.get("lean_source") or ""
        stderr = row.get("stderr") or ""
        return (
            f"{t(lang, 'lean_title')} #{row['attempt_id']}",
            "\n".join(
                [
                    f"{t(lang, 'proposition')}: {row.get('proposition_id', '-')}",
                    f"{t(lang, 'status')}: {status_label}",
                    f"{t(lang, 'lean_col_duration')}: {duration_text}",
                    (
                        f"{t(lang, 'lean_col_triage')}: "
                        f"{row.get('triage_difficulty', '-')} "
                        f"({reasons})"
                    ),
                    f"{t(lang, 'created')}: {row.get('created_at', '-')}",
                    "",
                    f"{t(lang, 'lean_source')}:",
                    lean_source or "-",
                    "",
                    f"{t(lang, 'stderr')}:",
                    stderr or "-",
                ]
            ),
        )
    if "report_id" in row and "file_path" in row:
        size = int(row.get("bytes") or 0)
        if size >= 1024 * 1024:
            size_label = f"{size / 1024 / 1024:.1f} MB"
        elif size >= 1024:
            size_label = f"{size / 1024:.1f} KB"
        else:
            size_label = f"{size} B"
        missing_marker = f"  [{t(lang, 'reports_missing_flag')}]" if row.get("missing") else ""
        return (
            f"{t(lang, 'reports_title')} #{row['report_id']}{missing_marker}",
            "\n".join(
                [
                    f"{t(lang, 'reports_col_kind')}: {row.get('kind', '-')}",
                    f"{t(lang, 'reports_col_node')}: {row.get('related_node_id') or '-'}",
                    f"{t(lang, 'reports_col_format')}: {row.get('format', '-')}",
                    f"{t(lang, 'reports_col_size')}: {size_label}",
                    f"{t(lang, 'reports_col_time')}: {row.get('generated_at', '-')}",
                    "",
                    f"{t(lang, 'path')}: {row.get('file_path', '-')}",
                    f"{t(lang, 'generated_by')}: {row.get('generated_by', '-')}",
                ]
            ),
        )
    if "pin_id" in row:
        return (
            f"{t(lang, 'claims')} {row['metric']}",
            "\n".join(
                [
                    f"{t(lang, 'value')}: {row['value']}",
                    f"{t(lang, 'dataset')}: {row['dataset']}",
                    f"{t(lang, 'verified')}: "
                    f"{t(lang, 'yes') if row['verified'] else t(lang, 'no')}",
                    f"{t(lang, 'seeds')}: {row['seeds']}",
                    f"{t(lang, 'claim_note')}: {row.get('note') or '-'}",
                    f"{t(lang, 'claim_source')}: {row.get('source_command') or '-'}",
                ]
            ),
        )
    return (
        f"{t(lang, 'literature')} {row['paper_id']}",
        "\n".join(
            [
                row.get("title", ""),
                f"{t(lang, 'year')}: {row.get('year') or '-'}",
                f"{t(lang, 'task')}: {row.get('task') or '-'}",
                f"{t(lang, 'score')}: {float(row.get('score') or 0.0):.2f}",
                f"{t(lang, 'lit_venue')}: {row.get('venue') or '-'}",
                f"{t(lang, 'lit_source')}: {row.get('source') or '-'}",
            ]
        ),
    )
