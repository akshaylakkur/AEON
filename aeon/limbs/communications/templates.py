"""HTML email templates for the AEON Hedge Fund Research Manager.

Professional, dark-themed templates with inline CSS for maximum email
client compatibility.  Designed to look like a Bloomberg Terminal meets
a hedge fund research report.

Color coding:
- Green (#00d97e) for bullish / positive
- Red (#ff4d4f) for bearish / negative
- Yellow / amber (#ffc107) for caution / neutral
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Shared style constants
# ---------------------------------------------------------------------------

_BG_DARK = "#1a1a2e"
_BG_CARD = "#16213e"
_BG_SECTION = "#0f3460"
_TEXT_PRIMARY = "#e4e6eb"
_TEXT_SECONDARY = "#a8a8b3"
_TEXT_MUTED = "#6c6c80"
_ACCENT = "#00d4ff"
_GREEN = "#00d97e"
_RED = "#ff4d4f"
_YELLOW = "#ffc107"
_BORDER = "#2a2a4a"
_FONT_STACK = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)


def _color_for_direction(direction: str) -> str:
    """Return the color hex for a trade direction."""
    d = direction.lower().strip()
    if d in ("buy", "long", "bullish", "overweight"):
        return _GREEN
    if d in ("sell", "short", "bearish", "underweight"):
        return _RED
    return _YELLOW  # hold, watch, neutral


def _color_for_confidence(conf: float) -> str:
    """Return a color based on confidence level."""
    if conf >= 0.7:
        return _GREEN
    if conf >= 0.4:
        return _YELLOW
    return _RED


def _confidence_bar(conf: float, width_px: int = 200) -> str:
    """Render an inline confidence bar as an HTML table cell hack."""
    pct = max(0.0, min(1.0, conf))
    filled = int(pct * width_px)
    color = _color_for_confidence(conf)
    return (
        f'<table cellpadding="0" cellspacing="0" border="0" '
        f'style="display:inline-table;vertical-align:middle;">'
        f'<tr>'
        f'<td style="width:{filled}px;height:8px;background:{color};'
        f'border-radius:4px 0 0 4px;"></td>'
        f'<td style="width:{width_px - filled}px;height:8px;'
        f'background:{_BORDER};border-radius:0 4px 4px 0;"></td>'
        f'</tr></table>'
        f' <span style="color:{color};font-weight:600;">{pct:.0%}</span>'
    )


def _escape(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _header_html(title: str) -> str:
    """Render the shared AEON branded header."""
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:linear-gradient(135deg, #0f3460 0%, #1a1a2e 100%);'
        f'border-radius:8px 8px 0 0;padding:24px 32px;">'
        f'<tr>'
        f'<td>'
        f'<div style="font-size:12px;letter-spacing:3px;color:{_ACCENT};'
        f'font-weight:700;margin-bottom:4px;font-family:{_FONT_STACK};">'
        f'AEON RESEARCH</div>'
        f'<div style="font-size:22px;font-weight:700;color:{_TEXT_PRIMARY};'
        f'font-family:{_FONT_STACK};">{_escape(title)}</div>'
        f'</td>'
        f'<td style="text-align:right;vertical-align:top;">'
        f'<div style="font-size:11px;color:{_TEXT_MUTED};'
        f'font-family:{_FONT_STACK};">'
        f'{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}'
        f'</div>'
        f'</td>'
        f'</tr></table>'
    )


def _footer_html() -> str:
    """Render the shared AEON branded footer with disclaimer."""
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border-top:1px solid {_BORDER};padding:20px 32px;'
        f'background:{_BG_DARK};border-radius:0 0 8px 8px;">'
        f'<tr><td>'
        f'<div style="font-size:11px;color:{_TEXT_MUTED};'
        f'line-height:1.5;font-family:{_FONT_STACK};">'
        f'<strong style="color:{_ACCENT};">AEON</strong> '
        f'Autonomous Economic Operating Node<br>'
        f'This is an AI-generated research report. It does not constitute '
        f'financial advice. All investment decisions are your responsibility. '
        f'Past performance does not guarantee future results.<br><br>'
        f'Reply to this email to steer future research focus.'
        f'</div>'
        f'</td></tr></table>'
    )


def _wrap_body(inner_html: str) -> str:
    """Wrap content in the full email document structure."""
    return (
        '<!DOCTYPE html>'
        '<html lang="en">'
        '<head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '</head>'
        f'<body style="margin:0;padding:0;background-color:#0d0d1a;'
        f'font-family:{_FONT_STACK};">'
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background-color:#0d0d1a;padding:20px 0;">'
        f'<tr><td align="center">'
        f'<table width="640" cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:640px;width:100%;background-color:{_BG_DARK};'
        f'border-radius:8px;border:1px solid {_BORDER};'
        f'box-shadow:0 4px 24px rgba(0,0,0,0.5);">'
        f'<tr><td>{inner_html}</td></tr>'
        f'</table>'
        f'</td></tr></table>'
        '</body></html>'
    )


# ---------------------------------------------------------------------------
# Public template functions
# ---------------------------------------------------------------------------


def research_update_html(
    subject: str,
    body: str,
    recommendations: list[dict[str, Any]] | None = None,
) -> str:
    """Generate HTML for a research update email.

    Args:
        subject: The email subject / report title.
        body: The main body text of the research update.
        recommendations: Optional list of recommendation dicts (see
            :func:`recommendation_card_html`).

    Returns:
        A complete HTML document string with inline CSS.
    """
    header = _header_html(subject)

    # Body section
    body_html = (
        f'<div style="padding:24px 32px;color:{_TEXT_PRIMARY};'
        f'font-size:14px;line-height:1.7;font-family:{_FONT_STACK};">'
    )
    # Convert newlines to paragraphs
    for paragraph in body.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        body_html += f'<p style="margin:0 0 16px 0;">{_escape(paragraph)}</p>'
    body_html += '</div>'

    # Recommendations section
    recs_html = ""
    if recommendations:
        recs_html = (
            f'<div style="padding:0 32px 24px 32px;">'
            f'<div style="font-size:13px;letter-spacing:2px;color:{_ACCENT};'
            f'font-weight:700;margin-bottom:16px;padding-top:8px;'
            f'border-top:1px solid {_BORDER};font-family:{_FONT_STACK};">'
            f'RECOMMENDATIONS</div>'
        )
        for rec in recommendations:
            recs_html += recommendation_card_html(rec)
        recs_html += '</div>'

    footer = _footer_html()
    return _wrap_body(header + body_html + recs_html + footer)


def urgent_alert_html(
    alert: str,
    recommended_action: str | None = None,
) -> str:
    """Generate HTML for an urgent alert email.

    Args:
        alert: The alert message.
        recommended_action: Optional recommended action text.

    Returns:
        A complete HTML document string.
    """
    header = _header_html("URGENT ALERT")

    alert_box = (
        f'<div style="padding:24px 32px;">'
        f'<div style="background:{_BG_CARD};border-left:4px solid {_RED};'
        f'padding:20px 24px;border-radius:0 6px 6px 0;'
        f'margin-bottom:16px;">'
        f'<div style="font-size:12px;letter-spacing:2px;color:{_RED};'
        f'font-weight:700;margin-bottom:8px;font-family:{_FONT_STACK};">'
        f'ALERT</div>'
        f'<div style="color:{_TEXT_PRIMARY};font-size:15px;line-height:1.6;'
        f'font-family:{_FONT_STACK};">{_escape(alert)}</div>'
        f'</div>'
    )

    action_html = ""
    if recommended_action:
        action_html = (
            f'<div style="background:{_BG_CARD};border-left:4px solid {_YELLOW};'
            f'padding:20px 24px;border-radius:0 6px 6px 0;">'
            f'<div style="font-size:12px;letter-spacing:2px;color:{_YELLOW};'
            f'font-weight:700;margin-bottom:8px;font-family:{_FONT_STACK};">'
            f'RECOMMENDED ACTION</div>'
            f'<div style="color:{_TEXT_PRIMARY};font-size:14px;line-height:1.6;'
            f'font-family:{_FONT_STACK};">{_escape(recommended_action)}</div>'
            f'</div>'
        )

    alert_box += action_html + '</div>'
    footer = _footer_html()
    return _wrap_body(header + alert_box + footer)


def daily_digest_html(summary: dict[str, Any]) -> str:
    """Generate HTML for a daily research digest email.

    Args:
        summary: Dict with keys like ``period_hours``, ``findings_count``,
            ``recommendations_count``, ``thoughts_count``,
            ``tool_calls_count``, ``top_findings`` (list of dicts),
            ``recent_recommendations`` (list of dicts),
            ``latest_steering``, ``daily_cost``.

    Returns:
        A complete HTML document string.
    """
    period = summary.get("period_hours", 24)
    header = _header_html(f"Research Digest ({period}h)")

    # Stats row
    findings_count = summary.get("findings_count", 0)
    recs_count = summary.get("recommendations_count", 0)
    thoughts_count = summary.get("thoughts_count", 0)
    tool_calls = summary.get("tool_calls_count", 0)
    daily_cost = summary.get("daily_cost", 0.0)

    stats_html = (
        f'<div style="padding:20px 32px;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr>'
    )
    stats = [
        ("Findings", str(findings_count), _ACCENT),
        ("Recommendations", str(recs_count), _GREEN),
        ("Thoughts", str(thoughts_count), _TEXT_SECONDARY),
        ("Tool Calls", str(tool_calls), _TEXT_SECONDARY),
    ]
    for label, value, color in stats:
        stats_html += (
            f'<td style="text-align:center;padding:12px 8px;'
            f'background:{_BG_CARD};border-radius:6px;">'
            f'<div style="font-size:24px;font-weight:700;color:{color};'
            f'font-family:{_FONT_STACK};">{value}</div>'
            f'<div style="font-size:11px;color:{_TEXT_MUTED};margin-top:4px;'
            f'font-family:{_FONT_STACK};">{label}</div>'
            f'</td>'
            f'<td style="width:8px;"></td>'
        )
    # Remove trailing spacer
    stats_html = stats_html.rsplit('<td style="width:8px;"></td>', 1)[0]
    stats_html += '</tr></table></div>'

    # Cost indicator
    cost_html = (
        f'<div style="padding:0 32px 16px 32px;text-align:right;">'
        f'<span style="font-size:11px;color:{_TEXT_MUTED};'
        f'font-family:{_FONT_STACK};">'
        f'LLM cost today: '
        f'<span style="color:{_ACCENT};font-weight:600;">'
        f'${daily_cost:.4f}</span></span></div>'
    )

    # Top findings
    findings_html = ""
    top_findings = summary.get("top_findings", [])
    if top_findings:
        findings_html = (
            f'<div style="padding:0 32px 20px 32px;">'
            f'<div style="font-size:13px;letter-spacing:2px;color:{_ACCENT};'
            f'font-weight:700;margin-bottom:12px;padding-top:8px;'
            f'border-top:1px solid {_BORDER};font-family:{_FONT_STACK};">'
            f'TOP FINDINGS</div>'
        )
        for f in top_findings[:5]:
            topic = f.get("topic", "General") if isinstance(f, dict) else str(f)
            finding = f.get("finding", "") if isinstance(f, dict) else ""
            importance = f.get("importance", 0.5) if isinstance(f, dict) else 0.5
            imp_color = _color_for_confidence(importance)
            findings_html += (
                f'<div style="background:{_BG_CARD};padding:12px 16px;'
                f'border-radius:6px;margin-bottom:8px;'
                f'border-left:3px solid {imp_color};">'
                f'<div style="font-size:11px;color:{_ACCENT};font-weight:600;'
                f'margin-bottom:4px;font-family:{_FONT_STACK};">'
                f'{_escape(topic)}</div>'
                f'<div style="font-size:13px;color:{_TEXT_PRIMARY};'
                f'line-height:1.5;font-family:{_FONT_STACK};">'
                f'{_escape(finding[:300])}</div>'
                f'</div>'
            )
        findings_html += '</div>'

    # Recent recommendations
    recs_html = ""
    recent_recs = summary.get("recent_recommendations", [])
    if recent_recs:
        recs_html = (
            f'<div style="padding:0 32px 20px 32px;">'
            f'<div style="font-size:13px;letter-spacing:2px;color:{_ACCENT};'
            f'font-weight:700;margin-bottom:12px;padding-top:8px;'
            f'border-top:1px solid {_BORDER};font-family:{_FONT_STACK};">'
            f'RECENT RECOMMENDATIONS</div>'
            f'<table width="100%" cellpadding="8" cellspacing="0" '
            f'border="0" style="border-collapse:collapse;">'
            f'<tr style="border-bottom:1px solid {_BORDER};">'
            f'<th style="text-align:left;font-size:11px;color:{_TEXT_MUTED};'
            f'font-weight:600;padding-bottom:8px;font-family:{_FONT_STACK};">'
            f'Asset</th>'
            f'<th style="text-align:center;font-size:11px;color:{_TEXT_MUTED};'
            f'font-weight:600;padding-bottom:8px;font-family:{_FONT_STACK};">'
            f'Direction</th>'
            f'<th style="text-align:center;font-size:11px;color:{_TEXT_MUTED};'
            f'font-weight:600;padding-bottom:8px;font-family:{_FONT_STACK};">'
            f'Confidence</th>'
            f'<th style="text-align:right;font-size:11px;color:{_TEXT_MUTED};'
            f'font-weight:600;padding-bottom:8px;font-family:{_FONT_STACK};">'
            f'Status</th>'
            f'</tr>'
        )
        for rec in recent_recs[:5]:
            asset = rec.get("asset", "?") if isinstance(rec, dict) else "?"
            direction = rec.get("direction", "?") if isinstance(rec, dict) else "?"
            confidence = rec.get("confidence", 0.0) if isinstance(rec, dict) else 0.0
            status = rec.get("status", "sent") if isinstance(rec, dict) else "sent"
            dir_color = _color_for_direction(direction)
            recs_html += (
                f'<tr style="border-bottom:1px solid {_BORDER};">'
                f'<td style="font-size:13px;color:{_TEXT_PRIMARY};'
                f'font-weight:600;font-family:{_FONT_STACK};">'
                f'{_escape(str(asset))}</td>'
                f'<td style="text-align:center;font-size:13px;'
                f'color:{dir_color};font-weight:700;'
                f'font-family:{_FONT_STACK};">'
                f'{_escape(str(direction).upper())}</td>'
                f'<td style="text-align:center;font-size:13px;'
                f'color:{_color_for_confidence(confidence)};'
                f'font-family:{_FONT_STACK};">'
                f'{confidence:.0%}</td>'
                f'<td style="text-align:right;font-size:12px;'
                f'color:{_TEXT_MUTED};font-family:{_FONT_STACK};">'
                f'{_escape(str(status))}</td>'
                f'</tr>'
            )
        recs_html += '</table></div>'

    # Steering input
    steering_html = ""
    latest_steering = summary.get("latest_steering")
    if latest_steering:
        steering_html = (
            f'<div style="padding:0 32px 20px 32px;">'
            f'<div style="font-size:13px;letter-spacing:2px;color:{_ACCENT};'
            f'font-weight:700;margin-bottom:12px;padding-top:8px;'
            f'border-top:1px solid {_BORDER};font-family:{_FONT_STACK};">'
            f'CURRENT STEERING</div>'
            f'<div style="background:{_BG_CARD};padding:12px 16px;'
            f'border-radius:6px;border-left:3px solid {_ACCENT};">'
            f'<div style="font-size:13px;color:{_TEXT_PRIMARY};'
            f'line-height:1.5;font-style:italic;'
            f'font-family:{_FONT_STACK};">'
            f'"{_escape(str(latest_steering)[:300])}"</div>'
            f'</div></div>'
        )

    footer = _footer_html()
    return _wrap_body(
        header + stats_html + cost_html + findings_html
        + recs_html + steering_html + footer
    )


def recommendation_card_html(rec: dict[str, Any]) -> str:
    """Generate HTML for a single recommendation card within an email.

    Args:
        rec: Dict with keys ``asset``, ``direction`` (buy/sell/hold),
            ``thesis`` or ``reasoning``, ``confidence`` (0-1),
            ``evidence`` (list of strings), ``risks`` (list of strings),
            ``timeframe``, ``key_metrics`` (dict).

    Returns:
        An HTML fragment (not a full document).
    """
    asset = rec.get("asset", "Unknown Asset")
    direction = rec.get("direction", rec.get("action", "WATCH"))
    thesis = rec.get("thesis", rec.get("reasoning", ""))
    confidence = rec.get("confidence", 0.0)
    evidence = rec.get("evidence", [])
    risks = rec.get("risks", [])
    timeframe = rec.get("timeframe", "")
    key_metrics = rec.get("key_metrics", {})

    dir_color = _color_for_direction(direction)

    card = (
        f'<div style="background:{_BG_CARD};border-radius:8px;'
        f'padding:20px 24px;margin-bottom:16px;'
        f'border:1px solid {_BORDER};">'
    )

    # Header: Asset + Direction badge
    card += (
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:center;margin-bottom:12px;">'
        f'<span style="font-size:18px;font-weight:700;'
        f'color:{_TEXT_PRIMARY};font-family:{_FONT_STACK};">'
        f'{_escape(str(asset))}</span>'
    )
    # Use a table-based badge for email compat
    card += (
        f'<table cellpadding="0" cellspacing="0" border="0" '
        f'style="display:inline-table;">'
        f'<tr><td style="background:{dir_color};color:#000;'
        f'font-size:12px;font-weight:800;letter-spacing:1px;'
        f'padding:4px 12px;border-radius:4px;'
        f'font-family:{_FONT_STACK};">'
        f'{_escape(str(direction).upper())}</td></tr></table>'
        f'</div>'
    )

    # Confidence bar
    card += (
        f'<div style="margin-bottom:16px;">'
        f'<span style="font-size:11px;color:{_TEXT_MUTED};'
        f'margin-right:8px;font-family:{_FONT_STACK};">Confidence</span>'
        f'{_confidence_bar(confidence)}'
        f'</div>'
    )

    # Thesis
    if thesis:
        card += (
            f'<div style="margin-bottom:16px;">'
            f'<div style="font-size:11px;letter-spacing:1px;color:{_ACCENT};'
            f'font-weight:600;margin-bottom:4px;'
            f'font-family:{_FONT_STACK};">THESIS</div>'
            f'<div style="font-size:14px;color:{_TEXT_PRIMARY};'
            f'line-height:1.6;font-family:{_FONT_STACK};">'
            f'{_escape(str(thesis))}</div>'
            f'</div>'
        )

    # Timeframe
    if timeframe:
        card += (
            f'<div style="margin-bottom:16px;">'
            f'<span style="font-size:11px;color:{_TEXT_MUTED};'
            f'font-family:{_FONT_STACK};">Timeframe: </span>'
            f'<span style="font-size:13px;color:{_TEXT_PRIMARY};'
            f'font-weight:600;font-family:{_FONT_STACK};">'
            f'{_escape(str(timeframe))}</span>'
            f'</div>'
        )

    # Key metrics table
    if key_metrics and isinstance(key_metrics, dict):
        card += (
            f'<div style="margin-bottom:16px;">'
            f'<div style="font-size:11px;letter-spacing:1px;color:{_ACCENT};'
            f'font-weight:600;margin-bottom:8px;'
            f'font-family:{_FONT_STACK};">KEY METRICS</div>'
            f'<table width="100%" cellpadding="6" cellspacing="0" '
            f'border="0" style="border-collapse:collapse;">'
        )
        for key, value in key_metrics.items():
            card += (
                f'<tr style="border-bottom:1px solid {_BORDER};">'
                f'<td style="font-size:12px;color:{_TEXT_MUTED};'
                f'font-family:{_FONT_STACK};">'
                f'{_escape(str(key))}</td>'
                f'<td style="font-size:13px;color:{_TEXT_PRIMARY};'
                f'font-weight:600;text-align:right;'
                f'font-family:{_FONT_STACK};">'
                f'{_escape(str(value))}</td>'
                f'</tr>'
            )
        card += '</table></div>'

    # Evidence
    if evidence:
        ev_list = evidence if isinstance(evidence, list) else [str(evidence)]
        card += (
            f'<div style="margin-bottom:16px;">'
            f'<div style="font-size:11px;letter-spacing:1px;color:{_ACCENT};'
            f'font-weight:600;margin-bottom:6px;'
            f'font-family:{_FONT_STACK};">EVIDENCE</div>'
        )
        for ev in ev_list[:5]:
            card += (
                f'<div style="font-size:13px;color:{_TEXT_SECONDARY};'
                f'line-height:1.5;padding-left:12px;margin-bottom:4px;'
                f'border-left:2px solid {_BORDER};'
                f'font-family:{_FONT_STACK};">'
                f'{_escape(str(ev)[:200])}</div>'
            )
        card += '</div>'

    # Risks
    if risks:
        risk_list = risks if isinstance(risks, list) else [str(risks)]
        card += (
            f'<div>'
            f'<div style="font-size:11px;letter-spacing:1px;color:{_RED};'
            f'font-weight:600;margin-bottom:6px;'
            f'font-family:{_FONT_STACK};">RISKS</div>'
        )
        for risk in risk_list[:5]:
            card += (
                f'<div style="font-size:13px;color:{_TEXT_SECONDARY};'
                f'line-height:1.5;padding-left:12px;margin-bottom:4px;'
                f'border-left:2px solid {_RED};'
                f'font-family:{_FONT_STACK};">'
                f'{_escape(str(risk)[:200])}</div>'
            )
        card += '</div>'

    card += '</div>'
    return card
