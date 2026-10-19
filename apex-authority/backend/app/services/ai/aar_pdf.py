"""Server-side PDF rendering from the STORED report (never from model output at export time)."""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.ai.repository import AARRecord


def _p(text: str, style) -> Paragraph:
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


def render_aar_pdf(rec: AARRecord) -> bytes:
    r = rec.report
    ss = getSampleStyleSheet()
    h1, h2, body = ss["Title"], ss["Heading2"], ss["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=9, textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("cell", parent=body, fontSize=8.5, leading=10.5)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=r.title, author="Apex Authority")
    flow = [_p(r.title, h1), _p("FICTIONAL TRAINING EXERCISE - AI-assisted draft, reviewed by an instructor"
                                if r.reviewed_at else "FICTIONAL TRAINING EXERCISE - UNREVIEWED AI-assisted draft", small), Spacer(1, 4 * mm)]
    start, end = rec.session_window
    meta = [["Scenario", rec.scenario_title], ["Session", str(r.session_id)],
            ["Session window (UTC)", f"{start.isoformat() if start else 'n/a'}  to  {end.isoformat() if end else 'n/a'}"],
            ["Report status", r.status.value], ["Reviewed at", r.reviewed_at.isoformat() if r.reviewed_at else "not reviewed"]]
    t = Table([[_p(a, cell), _p(b, cell)] for a, b in meta], colWidths=[40 * mm, 130 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flow += [t, Spacer(1, 4 * mm)]

    if rec.metrics_snapshot:
        flow.append(_p("Official session metrics (computed by the simulation platform)", h2))
        rows = [[_p(k, cell), _p("n/a" if v is None else v, cell)] for k, v in rec.metrics_snapshot.items()]
        mt = Table(rows, colWidths=[80 * mm, 40 * mm])
        mt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
        flow += [mt, Spacer(1, 3 * mm)]

    flow += [_p("Executive summary", h2), _p(r.executive_summary, body)]

    flow.append(_p("Key observations", h2))
    for o in r.key_observations:
        flow.append(_p(f"[{o.classification.value.upper()} | confidence: {o.confidence.value}] {o.observation}", body))
        flow.append(_p("Evidence: " + (", ".join(o.evidence_refs) or "none cited"), small))
    for title, items in (("Strengths", r.strengths), ("Areas for improvement", r.improvement_areas)):
        flow.append(_p(title, h2))
        for f in items:
            flow.append(_p("- " + f.text, body))
            flow.append(_p("Evidence: " + (", ".join(f.evidence_refs) or "none cited"), small))
    flow.append(_p("Recommendations", h2))
    for rec_item in r.recommendations:
        flow.append(_p(f"- {rec_item.text}", body))
        flow.append(_p(f"Learning objective: {rec_item.related_learning_objective}", small))
    flow.append(_p("Evidence limitations", h2))
    for lim in r.evidence_limitations or ["None recorded."]:
        flow.append(_p("- " + lim, body))
    flow += [_p("Follow-up scenario brief (draft)", h2), _p(r.follow_up_scenario_brief, body), Spacer(1, 6 * mm),
             _p(f"Generated with {r.model_provider} / {r.model_name}, prompt {r.prompt_version}. Narrative text is "
                "AI-assisted; scores and timestamps come from the simulation record.", small)]
    doc.build(flow)
    return buf.getvalue()
