"""Researcher results: participant feedback, classification correctness and
estimated cost saved, as a page (/admin/results) and an Excel file
(/admin/export.xlsx). Both need the admin token.

Saved cost compares the router with an all-LLM baseline in which every
email would get one general LLM reply. That baseline is estimated, not
measured, so the study's API cost doesn't double:
  - input tokens  = fixed prompt size + email length / CHARS_PER_TOKEN, where
    the fixed prompt size is measured from emails that did go to the general
    LLM (their input tokens minus their length / CHARS_PER_TOKEN, averaged);
  - output tokens = the average reply length of those same emails.
Actual cost counts every LLM call the router made (meeting extraction and
reply, exception notes, FAQ replies, general drafts). The classifier runs
on the server and has no per-email price, so it isn't counted.
"""

import io
import json
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse, Response

from app import db
from app.config import ADMIN_TOKEN, LLM_MODEL

router = APIRouter()

# USD per million tokens for LLM_MODEL (claude-sonnet-4-6). Update here if
# the model or its price changes.
PRICE_INPUT_PER_M = 3.0
PRICE_OUTPUT_PER_M = 15.0
CHARS_PER_TOKEN = 4
# The baseline needs this many general-LLM emails before it is reported.
MIN_BASELINE_EMAILS = 5
GENERAL_LLM_HANDLERS = {"llm"}


def _require_admin(token: Optional[str]) -> None:
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "bad or missing X-Admin-Token header")


def cost_usd(input_tokens: float, output_tokens: float) -> float:
    return (input_tokens * PRICE_INPUT_PER_M + output_tokens * PRICE_OUTPUT_PER_M) / 1_000_000


def baseline_model(events: list) -> Optional[dict]:
    """Fixed prompt size and average output, from general-LLM emails with
    cost data; None until there are MIN_BASELINE_EMAILS of them."""
    sample = [e for e in events if e["handler_used"] in GENERAL_LLM_HANDLERS
              and e["input_tokens"] is not None and e["body_chars"] is not None]
    if len(sample) < MIN_BASELINE_EMAILS:
        return None
    overhead = sum(e["input_tokens"] - e["body_chars"] / CHARS_PER_TOKEN for e in sample) / len(sample)
    output = sum(e["output_tokens"] for e in sample) / len(sample)
    return {"emails": len(sample), "prompt_tokens": max(overhead, 0.0), "output_tokens": output}


def _feedback_by_event() -> dict:
    """{email_event_id: {"correct": bool, "correct_category": str|None}};
    a later submission for the same day replaces the earlier one."""
    out = {}
    for s in db.list_all_checkin_submissions():
        for item in json.loads(s["per_email_json"] or "[]"):
            out[item.get("email_event_id")] = {
                "correct": item.get("correct"),
                "correct_category": item.get("correct_category"),
            }
    return out


def build_results(participant: Optional[str] = None, day: Optional[int] = None) -> dict:
    events = [dict(e) for e in db.list_email_events()]
    people = {p["id"]: p for p in db.list_participants_for_export()}
    feedback = _feedback_by_event()
    model = baseline_model(events)  # from all data, so filters don't move it

    rows = []
    for e in events:
        p = people.get(e["participant_id"])
        if p is None:
            continue
        study_day = db.study_day(p["connected_at"], e["created_at"])
        if participant and e["participant_id"] != participant:
            continue
        if day and study_day != day:
            continue
        has_cost = e["input_tokens"] is not None
        actual = cost_usd(e["input_tokens"], e["output_tokens"]) if has_cost else None
        baseline = None
        if model and has_cost and e["body_chars"] is not None:
            baseline = cost_usd(model["prompt_tokens"] + e["body_chars"] / CHARS_PER_TOKEN,
                                model["output_tokens"])
        fb = feedback.get(e["id"], {})
        rows.append({
            "participant": e["participant_id"], "email": p["email"], "role": p["role"],
            "day": study_day, "received": e["created_at"], "sender": e["sender"],
            "subject": e["subject"], "category": e["category"], "handler": e["handler_used"],
            "true_category": e["expected_category"],
            "verdict": {True: "correct", False: "wrong"}.get(fb.get("correct"), "not rated"),
            "should_be": fb.get("correct_category"),
            "draft": None if e["reply_needed"] is None else bool(e["reply_needed"]),
            "needs_review": None if e["needs_review"] is None else bool(e["needs_review"]),
            "input_tokens": e["input_tokens"], "output_tokens": e["output_tokens"],
            "latency_ms": e["latency_ms"], "cost_usd": actual, "baseline_usd": baseline,
        })
    return {"rows": rows, "summary": summarise(rows, model),
            "confusion": confusion(rows), "by_category": by_category(rows),
            "by_true_category": by_true_category(rows),
            "participants": list(people.values()),
            "baseline": model, "model": LLM_MODEL,
            "prices": {"input_per_m": PRICE_INPUT_PER_M, "output_per_m": PRICE_OUTPUT_PER_M}}


def summarise(rows: list, model: Optional[dict]) -> dict:
    rated = [r for r in rows if r["verdict"] != "not rated"]
    costed = [r for r in rows if r["cost_usd"] is not None]
    avoided = [r for r in costed if (r["input_tokens"] or 0) + (r["output_tokens"] or 0) == 0]
    actual = sum(r["cost_usd"] for r in costed)
    s = {
        "emails": len(rows),
        "rated": len(rated),
        "correct": sum(r["verdict"] == "correct" for r in rated),
        "correct_pct": round(100 * sum(r["verdict"] == "correct" for r in rated) / len(rated), 1) if rated else None,
        "with_cost_data": len(costed),
        "llm_calls_avoided": len(avoided),
        "llm_calls_avoided_pct": round(100 * len(avoided) / len(costed), 1) if costed else None,
        "actual_usd": round(actual, 4),
        "baseline_usd": None, "saved_usd": None, "saved_pct": None,
        "avg_latency_ms": round(sum(r["latency_ms"] or 0 for r in costed) / len(costed), 1) if costed else None,
    }
    labelled = [r for r in rows if r["true_category"]]
    s["with_true_label"] = len(labelled)
    s["model_correct"] = sum(r["category"] == r["true_category"] for r in labelled)
    s["model_correct_pct"] = round(100 * s["model_correct"] / len(labelled), 1) if labelled else None
    if model and costed:
        baseline = sum(r["baseline_usd"] for r in costed if r["baseline_usd"] is not None)
        s["baseline_usd"] = round(baseline, 4)
        s["saved_usd"] = round(baseline - actual, 4)
        s["saved_pct"] = round(100 * (baseline - actual) / baseline, 1) if baseline else None
    return s


def by_category(rows: list) -> list:
    out = {}
    for r in rows:
        c = out.setdefault(r["category"], {"category": r["category"], "emails": 0, "rated": 0, "correct": 0})
        c["emails"] += 1
        if r["verdict"] != "not rated":
            c["rated"] += 1
            c["correct"] += r["verdict"] == "correct"
    for c in out.values():
        c["correct_pct"] = round(100 * c["correct"] / c["rated"], 1) if c["rated"] else None
    return sorted(out.values(), key=lambda c: -c["emails"])


def by_true_category(rows: list) -> list:
    """Study emails per category they were written as: how many the
    classifier got right (recall), and what it said instead."""
    out = {}
    for r in rows:
        if not r["true_category"]:
            continue
        c = out.setdefault(r["true_category"], {"category": r["true_category"], "emails": 0,
                                                "model_correct": 0, "predicted_instead": {}})
        c["emails"] += 1
        if r["category"] == r["true_category"]:
            c["model_correct"] += 1
        else:
            c["predicted_instead"][r["category"]] = c["predicted_instead"].get(r["category"], 0) + 1
    for c in out.values():
        c["model_correct_pct"] = round(100 * c["model_correct"] / c["emails"], 1)
    return sorted(out.values(), key=lambda c: c["category"])


def confusion(rows: list) -> list:
    """Rated emails as (predicted, participant says, count). Correct ones
    count as predicted == said; Wrong without a chosen category is
    'unknown'."""
    counts = {}
    for r in rows:
        if r["verdict"] == "not rated":
            continue
        said = r["category"] if r["verdict"] == "correct" else (r["should_be"] or "unknown")
        counts[(r["category"], said)] = counts.get((r["category"], said), 0) + 1
    return [{"predicted": p, "participant_says": s, "count": n}
            for (p, s), n in sorted(counts.items(), key=lambda kv: -kv[1])]


@router.get("/admin/results.json")
def results_json(participant: Optional[str] = None, day: Optional[int] = None,
                 x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    return build_results(participant, day)


@router.get("/admin/export.xlsx")
def export_xlsx(x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    from openpyxl import Workbook
    from openpyxl.styles import Font

    data = build_results()
    wb = Workbook()

    def sheet(title, header, records, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for rec in records:
            ws.append(rec)
        ws.freeze_panes = "A2"
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col[:200])
            ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 60)

    s, b = data["summary"], data["baseline"]
    sheet("Summary", ["Measure", "Value"], [
        ["Emails processed", s["emails"]],
        ["Emails rated by participants", s["rated"]],
        ["Rated correct (%)", s["correct_pct"]],
        ["Emails with cost data", s["with_cost_data"]],
        ["LLM calls avoided", s["llm_calls_avoided"]],
        ["LLM calls avoided (%)", s["llm_calls_avoided_pct"]],
        ["Actual LLM cost (USD)", s["actual_usd"]],
        ["Estimated all-LLM cost (USD)", s["baseline_usd"]],
        ["Estimated saved (USD)", s["saved_usd"]],
        ["Estimated saved (%)", s["saved_pct"]],
        ["Average handler latency (ms)", s["avg_latency_ms"]],
        ["Study emails with a true label", s["with_true_label"]],
        ["Classifier correct vs. true label (%)", s["model_correct_pct"]],
        ["Model", data["model"]],
        ["Price input / output (USD per 1M tokens)", f"{PRICE_INPUT_PER_M} / {PRICE_OUTPUT_PER_M}"],
        ["Baseline: general-LLM emails used", b["emails"] if b else "not enough data yet"],
        ["Baseline: fixed prompt tokens", round(b["prompt_tokens"], 1) if b else None],
        ["Baseline: average output tokens", round(b["output_tokens"], 1) if b else None],
    ], first=True)
    sheet("Emails", ["Participant", "Role", "Day", "Received (UTC)", "Sender", "Subject",
                     "Category", "True category", "Handler", "Draft", "Needs review", "Participant verdict",
                     "Should be", "Input tokens", "Output tokens", "Latency (ms)",
                     "Cost (USD)", "All-LLM estimate (USD)"],
          [[r["participant"], r["role"], r["day"], r["received"], r["sender"], r["subject"],
            r["category"], r["true_category"], r["handler"], r["draft"], r["needs_review"], r["verdict"],
            r["should_be"], r["input_tokens"], r["output_tokens"], r["latency_ms"],
            r["cost_usd"], r["baseline_usd"]] for r in data["rows"]])
    sheet("By category", ["Category", "Emails", "Rated", "Correct", "Correct (%)"],
          [[c["category"], c["emails"], c["rated"], c["correct"], c["correct_pct"]]
           for c in data["by_category"]])
    sheet("True labels", ["True category", "Study emails", "Classifier correct", "Correct (%)", "Predicted instead"],
          [[c["category"], c["emails"], c["model_correct"], c["model_correct_pct"],
            ", ".join(f"{k} {v}" for k, v in c["predicted_instead"].items())]
           for c in data["by_true_category"]])
    sheet("Confusion", ["Predicted", "Participant says", "Count"],
          [[c["predicted"], c["participant_says"], c["count"]] for c in data["confusion"]])
    sheet("Feedback", ["Participant", "Day", "Overall rating (1-10)", "Notes", "Submitted (UTC)"],
          [[f["participant_id"], f["day_number"], f["overall_rating"], f["notes"], f["submitted_at"]]
           for f in db.list_all_checkin_submissions()])
    sheet("Participants", ["Participant", "Email", "Role", "Connected (UTC)", "Active", "Days checked in"],
          [[p["id"], p["email"], p["role"], p["connected_at"], bool(p["active"]), p["days_checked_in"]]
           for p in data["participants"]])

    buf = io.BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=study_results.xlsx"},
    )


@router.get("/admin/results", response_class=HTMLResponse)
def results_page():
    """The page itself holds no data: it asks for the admin token, keeps it
    in this browser tab only (sessionStorage), and loads /admin/results.json.
    All email text is inserted with textContent, never as HTML."""
    return RESULTS_HTML


RESULTS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Study results</title>
<style>
:root{--bg:#F4F5F7;--card:#fff;--ink:#1B1F27;--muted:#5F6673;--rule:#E1E4EA;--accent:#24508F;
  --good:#2F7A4F;--bad:#A33A2E;--soft:#EEF2F8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,system-ui,"Segoe UI",sans-serif;padding:28px 16px 48px}
main{max-width:1240px;margin:0 auto;display:flex;flex-direction:column;gap:20px}
h1{font-size:22px;margin:0}
h2{font-size:15px;margin:0 0 10px}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input,select,button{font:inherit;padding:7px 10px;border:1px solid var(--rule);border-radius:8px;background:#fff;color:var(--ink)}
button{cursor:pointer;background:var(--accent);color:#fff;border-color:var(--accent);font-weight:600}
button.secondary{background:#fff;color:var(--accent)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:12px 14px}
.card b{display:block;font-size:22px;font-variant-numeric:tabular-nums}
.card span{color:var(--muted);font-size:12.5px}
.panel{background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:14px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);background:var(--soft);white-space:nowrap}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.v-correct{color:var(--good);font-weight:600}.v-wrong{color:var(--bad);font-weight:600}.v-not{color:var(--muted)}
.muted{color:var(--muted)}.err{color:var(--bad)}
td.subj{min-width:260px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
</style></head>
<body><main>
  <h1>Study results</h1>
  <div class="bar">
    <input id="tok" type="password" placeholder="Admin token" aria-label="Admin token">
    <button id="load">Load results</button>
    <select id="who" aria-label="Participant"><option value="">All participants</option></select>
    <select id="day" aria-label="Day"><option value="">All days</option></select>
    <button id="xlsx" class="secondary">Download Excel</button>
    <span id="msg" class="muted"></span>
  </div>
  <div class="cards" id="cards"></div>
  <p class="muted" id="costnote"></p>
  <div class="two">
    <div class="panel"><h2>Correct by category</h2><div class="scroll"><table id="bycat"></table></div></div>
    <div class="panel"><h2>Predicted vs. what participants said</h2><div class="scroll"><table id="conf"></table></div></div>
  </div>
  <div class="panel"><h2>Classifier vs. true label (study emails)</h2><div class="scroll"><table id="truth"></table></div></div>
  <div class="panel"><h2>Emails</h2><div class="scroll"><table id="rows"></table></div></div>
</main>
<script>
const $ = id => document.getElementById(id);
try { $('tok').value = sessionStorage.getItem('adminToken') || ''; } catch (e) {}
const fmt = (v, d) => v === null || v === undefined ? '—' : (typeof v === 'number' ? v.toFixed(d ?? 0) : v);
const usd = v => v === null || v === undefined ? '—' : '$' + v.toFixed(v < 1 ? 4 : 2);

function table(el, header, rows) {
  el.replaceChildren();
  const tr = el.insertRow();
  header.forEach(([h]) => { const th = document.createElement('th'); th.textContent = h; tr.appendChild(th); });
  if (!rows.length) { const r = el.insertRow(); const c = r.insertCell(); c.colSpan = header.length; c.textContent = 'Nothing yet.'; c.className = 'muted'; }
  rows.forEach(row => {
    const r = el.insertRow();
    row.forEach((v, i) => { const c = r.insertCell(); c.textContent = v; if (header[i][1]) c.className = header[i][1]; });
  });
  return el;
}

async function load() {
  const tok = $('tok').value;
  try { sessionStorage.setItem('adminToken', tok); } catch (e) {}
  const q = new URLSearchParams();
  if ($('who').value) q.set('participant', $('who').value);
  if ($('day').value) q.set('day', $('day').value);
  $('msg').textContent = 'Loading…';
  const res = await fetch('/admin/results.json?' + q, {headers: {'X-Admin-Token': tok}});
  if (!res.ok) { $('msg').textContent = res.status === 401 ? 'Wrong admin token.' : 'Could not load results.'; $('msg').className = 'err'; return; }
  const d = await res.json();
  $('msg').textContent = ''; $('msg').className = 'muted';

  const who = $('who').value, day = $('day').value;
  $('who').replaceChildren(new Option('All participants', ''), ...d.participants.map(p => new Option(`${p.email} (${p.role || 'no role'})`, p.id)));
  $('who').value = who;
  const days = [...new Set(d.rows.map(r => r.day))].sort((a, b) => a - b);
  $('day').replaceChildren(new Option('All days', ''), ...days.map(n => new Option('Day ' + n, n)));
  $('day').value = day;

  const s = d.summary;
  const cards = [
    [s.emails, 'emails processed'],
    [s.model_correct_pct === null ? '—' : s.model_correct_pct + '%', `classifier correct vs. true label (${s.model_correct} of ${s.with_true_label})`],
    [s.correct_pct === null ? '—' : s.correct_pct + '%', `rated correct by participants (${s.correct} of ${s.rated} rated)`],
    [s.llm_calls_avoided_pct === null ? '—' : s.llm_calls_avoided_pct + '%', `LLM calls avoided (${s.llm_calls_avoided} of ${s.with_cost_data})`],
    [usd(s.actual_usd), 'actual LLM cost'],
    [usd(s.baseline_usd), 'estimated all-LLM cost'],
    [s.saved_usd === null ? '—' : usd(s.saved_usd) + (s.saved_pct === null ? '' : ` (${s.saved_pct}%)`), 'estimated saved'],
  ];
  $('cards').replaceChildren(...cards.map(([v, l]) => {
    const c = document.createElement('div'); c.className = 'card';
    const b = document.createElement('b'); b.textContent = v; const sp = document.createElement('span'); sp.textContent = l;
    c.append(b, sp); return c;
  }));
  const b = d.baseline;
  $('costnote').textContent = b
    ? `All-LLM estimate: ${b.prompt_tokens.toFixed(0)} prompt tokens + email length ÷ 4 in, ${b.output_tokens.toFixed(0)} tokens out, measured from ${b.emails} emails drafted by the general LLM. ${d.model} at $${d.prices.input_per_m} / $${d.prices.output_per_m} per million input / output tokens. Emails processed before cost tracking are left out of cost totals.`
    : `Cost saved appears once at least 5 emails have been drafted by the general LLM. ${d.model} at $${d.prices.input_per_m} / $${d.prices.output_per_m} per million input / output tokens.`;

  table($('bycat'), [['Category'], ['Emails', 'n'], ['Rated', 'n'], ['Correct %', 'n']],
    d.by_category.map(c => [c.category, c.emails, c.rated, fmt(c.correct_pct, 1)]));
  table($('truth'), [['True category'], ['Study emails', 'n'], ['Classifier correct %', 'n'], ['Predicted instead']],
    d.by_true_category.map(c => [c.category, c.emails, fmt(c.model_correct_pct, 1),
      Object.entries(c.predicted_instead).map(([k, v]) => `${k} ${v}`).join(', ')]));
  table($('conf'), [['Predicted'], ['Participant says'], ['Emails', 'n']],
    d.confusion.map(c => [c.predicted, c.participant_says, c.count]));
  const t = table($('rows'), [['Day', 'n'], ['Participant'], ['Subject', 'subj'], ['Sender'], ['Category'], ['True category'], ['Handler'],
      ['Verdict'], ['Should be'], ['Tokens in/out', 'n'], ['Cost', 'n'], ['All-LLM est.', 'n']],
    d.rows.map(r => [r.day, r.email, r.subject || '(no subject)', r.sender, r.category, r.true_category || '', r.handler,
      r.verdict, r.should_be || '', r.input_tokens === null ? '—' : `${r.input_tokens} / ${r.output_tokens}`,
      usd(r.cost_usd), usd(r.baseline_usd)]));
  [...t.rows].slice(1).forEach(tr => { const c = tr.cells[7]; if (c) c.className = c.textContent === 'correct' ? 'v-correct' : c.textContent === 'wrong' ? 'v-wrong' : 'v-not'; });
}

async function download() {
  const res = await fetch('/admin/export.xlsx', {headers: {'X-Admin-Token': $('tok').value}});
  if (!res.ok) { $('msg').textContent = res.status === 401 ? 'Wrong admin token.' : 'Download failed.'; $('msg').className = 'err'; return; }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(await res.blob()); a.download = 'study_results.xlsx'; a.click();
  URL.revokeObjectURL(a.href);
}

$('load').onclick = load; $('who').onchange = load; $('day').onchange = load; $('xlsx').onclick = download;
if ($('tok').value) load();
</script>
</body></html>
"""
