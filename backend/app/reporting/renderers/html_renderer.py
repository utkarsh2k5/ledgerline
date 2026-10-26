"""IR -> single self-contained interactive HTML file (click any number to trace it)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from jinja2 import Environment, select_autoescape

from ...analytics.facts import FactBook, fmt
from ..ir import Callout, Chart, Commentary, Document, KPIGrid, Paragraph, Table
from . import theme as T

_env = Environment(autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)

TEMPLATE = _env.from_string(r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ doc.title }} · {{ doc.scheme_name }}</title>
<style>
:root{--navy:#17324d;--ink:#1b1b1b;--ink2:#52514e;--ink3:#8a8984;--rule:#e2e0d9;--band:#f3f2ee;--bg:#fbfbf9;
--good:#0b7a3e;--bad:#c0392b;--warnbg:#fff4d6;--warn:#7a5200;--accent:#2a78d6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{background:var(--navy);color:#fff;padding:48px 16px 40px}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
header .eyebrow{color:#9ec5f4;font-weight:700;letter-spacing:.08em;font-size:12px;text-transform:uppercase}
header h1{font-size:36px;margin:6px 0 4px;line-height:1.15}header p{margin:0;color:#dce6f2}
nav{position:sticky;top:0;background:#fff;border-bottom:1px solid var(--rule);z-index:5;overflow-x:auto;white-space:nowrap}
nav a{display:inline-block;padding:10px 12px;color:var(--ink2);text-decoration:none;font-size:13px}nav a:hover{color:var(--navy)}
section{background:#fff;border:1px solid var(--rule);border-radius:10px;padding:24px;margin:20px 0}
h2{color:var(--navy);font-size:20px;margin:0 0 14px}h3{font-size:14px;color:var(--ink2);margin:18px 0 8px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.kpi{background:var(--band);border-radius:8px;padding:14px 16px}.kpi .l{font-size:11px;font-weight:700;color:var(--ink2);text-transform:uppercase;letter-spacing:.04em}
.kpi .v{font-size:26px;font-weight:700;color:var(--navy);margin-top:4px}.kpi .s{font-size:13px}
.tbl{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
th{background:var(--navy);color:#fff;font-weight:600;padding:8px 10px;text-align:right;white-space:nowrap}th:first-child{text-align:left}
td{padding:7px 10px;border-bottom:1px solid var(--rule);text-align:right}td.l{text-align:left}tr.b td{font-weight:700;background:var(--band)}
.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.note{color:var(--ink3);font-size:12.5px;font-style:italic;margin:6px 0 0}.lead{color:var(--ink2)}
.fact{cursor:pointer;border-bottom:1px dotted var(--ink3)}.fact:hover,.fact:focus{background:#e8f1fc;outline:none}
img.chart{width:100%;height:auto;display:block}
.commentary p{font-size:16px;line-height:1.65;margin:0 0 10px}
.badge{display:inline-block;font-size:12.5px;padding:4px 10px;border-radius:99px;margin-top:6px}
.badge.ok{background:#e3f4ea;color:var(--good)}.badge.fb{background:var(--warnbg);color:var(--warn)}
.callout{background:var(--warnbg);color:var(--warn);padding:14px 16px;border-radius:8px}
#panel{position:fixed;top:0;right:0;width:min(520px,100%);height:100%;background:#fff;box-shadow:-8px 0 30px rgba(0,0,0,.15);
transform:translateX(105%);transition:transform .2s;z-index:20;display:flex;flex-direction:column}
#panel.open{transform:none}#panel header{padding:16px 20px;background:var(--navy)}#panel header h3{color:#fff;margin:0;font-size:16px}
#panel header button{float:right;background:none;border:0;color:#fff;font-size:22px;cursor:pointer;line-height:1}
#trace{overflow:auto;padding:16px 20px;flex:1}
.node{border-left:2px solid var(--rule);padding:4px 0 4px 12px;margin:6px 0}
.node>.h{font-weight:600}.node .val{color:var(--navy);font-weight:700;font-variant-numeric:tabular-nums}
.node .f{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--ink2);background:var(--band);padding:4px 6px;border-radius:4px;margin:4px 0;word-break:break-word}
.node .src{font-size:12px;color:var(--accent);word-break:break-all}
.node button.more{background:none;border:1px solid var(--rule);border-radius:4px;font-size:12px;padding:2px 8px;cursor:pointer;color:var(--ink2)}
.hint{font-size:13px;color:var(--ink2)}footer{color:var(--ink3);font-size:12px;padding:20px 0 40px}
@media (max-width:640px){header h1{font-size:26px}section{padding:16px}}
</style></head><body>
<header><div class="wrap"><div class="eyebrow">{{ doc.scheme_name }}</div><h1>{{ doc.title }}</h1>
<p>{{ doc.subtitle }} · Prepared for {{ doc.prepared_for }}</p></div></header>
<nav><div class="wrap">{% for s in sections %}<a href="#s{{ loop.index }}">{{ s.title }}</a>{% endfor %}</div></nav>
<main class="wrap">
<p class="hint" style="margin-top:18px">Tip: click any underlined number to see exactly how it was calculated and which source rows it came from.</p>
{% for s in sections %}<section id="s{{ loop.index }}"><h2>{{ s.title }}</h2>
{% for b in s.blocks %}{{ b|safe }}{% endfor %}</section>{% endfor %}
<footer>Generated by Ledgerline · content fingerprint <code>{{ fingerprint[:16] }}</code> · spec <code>{{ doc.meta.spec }}</code></footer>
</main>
<aside id="panel" aria-hidden="true"><header><button onclick="closePanel()" aria-label="Close">×</button><h3>Where does this number come from?</h3></header><div id="trace"></div></aside>
<script id="facts" type="application/json">{{ facts_json|safe }}</script>
<script>
const FACTS = JSON.parse(document.getElementById('facts').textContent);
const panel = document.getElementById('panel'), trace = document.getElementById('trace');
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function node(id, depth){
  const f = FACTS[id]; if(!f) return `<div class="node">${esc(id)} (not embedded)</div>`;
  let h = `<div class="node"><div class="h">${esc(f.label)} = <span class="val">${esc(f.display)}</span></div>`;
  h += `<div class="f">${esc(f.formula)}</div>`;
  if (f.sources && f.sources.length) h += f.sources.map(s=>`<div class="src">⤷ ${esc(s)}</div>`).join('');
  if (f.inputs && f.inputs.length){
    if (depth < 1) { h += f.inputs.slice(0,24).map(i=>node(i, depth+1)).join(''); if (f.inputs.length>24) h += `<div class="hint">…and ${f.inputs.length-24} more inputs</div>`; }
    else h += `<button class="more" data-id="${esc(id)}">Show ${f.inputs.length} input figure${f.inputs.length>1?'s':''}</button>`;
  }
  return h + '</div>';
}
function openFact(id){ trace.innerHTML = node(id, 0); panel.classList.add('open'); panel.setAttribute('aria-hidden','false'); }
function closePanel(){ panel.classList.remove('open'); panel.setAttribute('aria-hidden','true'); }
document.addEventListener('click', e => {
  const t = e.target.closest('[data-fact]'); if (t) { openFact(t.dataset.fact); return; }
  const m = e.target.closest('button.more'); if (m) { m.outerHTML = FACTS[m.dataset.id].inputs.slice(0,24).map(i=>node(i,1)).join(''); }
});
document.addEventListener('keydown', e => { if (e.key==='Escape') closePanel();
  if ((e.key==='Enter'||e.key===' ') && e.target.dataset && e.target.dataset.fact){ e.preventDefault(); openFact(e.target.dataset.fact);} });
</script></body></html>""")


def _e(s: str) -> str:
    from markupsafe import escape
    return str(escape(s))


def _fact_span(text: str, fid: str | None, cls: str = "") -> str:
    if not fid:
        return f'<span class="{cls}">{_e(text)}</span>' if cls else _e(text)
    return f'<span class="fact {cls}" tabindex="0" data-fact="{_e(fid)}">{_e(text)}</span>'


def _block_html(b) -> str:
    if isinstance(b, KPIGrid):
        cards = []
        for k in b.items:
            sub = f'<div class="s {k.tone}">{_fact_span(k.sub, k.sub_fact_id)}</div>' if k.sub else ""
            cards.append(f'<div class="kpi"><div class="l">{_e(k.label)}</div><div class="v">{_fact_span(k.display, k.fact_id)}</div>{sub}</div>')
        return f'<div class="kpis">{"".join(cards)}</div>'
    if isinstance(b, Table):
        head = "".join(f"<th>{_e(c)}</th>" for c in b.columns)
        rows = []
        for row in b.rows:
            bold = any(c.bold for c in row)
            tds = "".join(f'<td class="{"l" if c.align == "left" else ""} {c.tone if c.tone != "neutral" else ""}">'
                          f'{_fact_span(c.text, c.fact_id)}</td>' for c in row)
            rows.append(f'<tr class="{"b" if bold else ""}">{tds}</tr>')
        cap = f"<h3>{_e(b.caption)}</h3>" if b.caption else ""
        note = f'<p class="note">{_e(b.note)}</p>' if b.note else ""
        return f'{cap}<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>{note}'
    if isinstance(b, Chart):
        if not b.image:
            return ""
        data = base64.b64encode(Path(b.image).read_bytes()).decode()
        cap = f'<p class="note">{_e(b.caption)}</p>' if b.caption else ""
        return f'<h3>{_e(b.title)}</h3><img class="chart" alt="{_e(b.title)}" src="data:image/png;base64,{data}">{cap}'
    if isinstance(b, Commentary):
        paras = "".join(f"<p>{_e(p.strip())}</p>" for p in b.text.split("\n\n"))
        badge = ("ok", "✓ ") if b.status == "verified" else ("fb", "ⓘ ")
        return (f'<div class="commentary">{paras}</div>'
                f'<span class="badge {badge[0]}">{badge[1]}{_e(T.status_line(b.status, b.provider, b.issues))}</span>')
    if isinstance(b, Callout):
        return f'<div class="callout">{_e(b.text)}</div>'
    if isinstance(b, Paragraph):
        cls = {"note": "note", "lead": "lead"}.get(b.style, "")
        return f'<p class="{cls}">{_e(b.text)}</p>'
    return ""


def render_html(doc: Document, facts: FactBook, fingerprint: str, path: Path) -> Path:
    used = facts.subset(doc.fact_ids())
    facts_json = json.dumps(
        {f.id: {**f.to_dict(), "display": fmt(f.value, f.unit, facts.currency)} for f in used.all()},
        separators=(",", ":"),
    ).replace("</", "<\\/")
    sections = [{"title": s.title, "blocks": [_block_html(b) for b in s.blocks]} for s in doc.sections]
    html = TEMPLATE.render(doc=doc, sections=sections, facts_json=facts_json, fingerprint=fingerprint)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
