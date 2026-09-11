"""A single-file HTML board: every claim, and how much of its life it has used."""

from __future__ import annotations

import html
from datetime import datetime, timezone

from . import config, state
from .core import Result, Status

ORDER = [Status.ERROR, Status.INCONSISTENT, Status.DRIFT, Status.STALE,
         Status.ORPHAN, Status.SKIPPED, Status.NEW, Status.OK]

BLURB = {
    Status.ERROR: "the command would not run",
    Status.INCONSISTENT: "one claim, several numbers",
    Status.DRIFT: "the document and the command disagree",
    Status.STALE: "nobody has stood behind this in too long",
    Status.ORPHAN: "configured, but no longer written anywhere",
    Status.SKIPPED: "not re-run this time",
    Status.NEW: "seen for the first time",
    Status.OK: "still true",
}

CSS = """
:root{color-scheme:light dark;
  --bg:#fbfaf8;--card:#fff;--ink:#1b1a18;--dim:#6f6a63;--line:#e5e1da;
  --ok:#2f7d55;--warn:#b06f14;--bad:#b23a35;--track:#eceae5;}
@media (prefers-color-scheme:dark){:root{
  --bg:#14140f;--card:#1c1c17;--ink:#efece5;--dim:#9a958c;--line:#2e2e27;
  --ok:#63b487;--warn:#d8a24a;--bad:#e0736c;--track:#262620;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif;}
.wrap{max-width:52rem;margin:0 auto;padding:3rem 1.25rem 5rem}
h1{font-size:1.6rem;margin:0 0 .3rem;letter-spacing:-.02em}
.sub{color:var(--dim);margin:0 0 2.25rem;font-size:.9rem}
.sub em{font-style:normal;color:var(--ink)}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
  margin:2.25rem 0 .65rem;font-weight:600}
h2 small{text-transform:none;letter-spacing:0;font-weight:400;opacity:.8}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:.85rem 1rem;margin-bottom:.5rem}
.row{display:flex;gap:.75rem;align-items:baseline;flex-wrap:wrap}
.name{font-weight:600}
.val{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.95rem;
  background:var(--track);padding:.05rem .4rem;border-radius:5px}
.was{color:var(--dim);text-decoration:line-through}
.where{color:var(--dim);font-size:.82rem;margin-left:auto;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.why{color:var(--dim);font-size:.87rem;margin-top:.35rem}
.msg{font-size:.87rem;margin-top:.35rem}
.bar{height:4px;background:var(--track);border-radius:2px;margin-top:.6rem;overflow:hidden}
.bar i{display:block;height:100%;border-radius:2px;min-width:2px}
.bar.ok i{background:var(--ok)}
.bar.warn i{background:var(--warn)}
.bar.bad i{background:var(--bad)}
.card.bad .name{color:var(--bad)}
.card.warn .name{color:var(--warn)}
.empty{color:var(--dim)}
footer{margin-top:3.5rem;color:var(--dim);font-size:.8rem;border-top:1px solid var(--line);
  padding-top:1rem}
"""

TONE = {
    Status.ERROR: "bad", Status.INCONSISTENT: "bad", Status.DRIFT: "bad",
    Status.STALE: "warn", Status.ORPHAN: "warn", Status.SKIPPED: "ok",
    Status.NEW: "ok", Status.OK: "ok",
}


def _life(result: Result) -> float:
    """How much of the claim's shelf life has been used, 0..1."""
    if not result.claim.every or result.age is None:
        return 0.0
    return max(0.0, min(1.0, result.age / result.claim.every))


def _card(result: Result) -> str:
    tone = TONE[result.status]
    e = html.escape
    bits = [f'<span class="name">{e(result.name)}</span>']
    if result.status is Status.DRIFT and result.produced:
        bits.append(f'<span class="val was">{e(result.document)}</span>')
        bits.append(f'<span class="val">{e(result.produced)}</span>')
    elif result.document:
        bits.append(f'<span class="val">{e(result.document)}</span>')
    bits.append(f'<span class="where">{e(result.where)}</span>')

    extra = ""
    if result.claim.why:
        extra += f'<div class="why">{e(result.claim.why)}</div>'
    if result.message and result.status is not Status.OK:
        extra += f'<div class="msg">{e(result.message)}</div>'
    if result.claim.every:
        life = _life(result)
        spent = "bad" if life >= 1 else "warn" if life >= 0.7 else "ok"
        extra += (f'<div class="bar {spent}" title="{life * 100:.0f}% of its shelf life used">'
                  f'<i style="width:{life * 100:.1f}%"></i></div>')

    return f'<div class="card {tone}"><div class="row">{"".join(bits)}</div>{extra}</div>'


def render(results: list[Result], title: str = "") -> str:
    e = html.escape
    by_status: dict[Status, list[Result]] = {}
    for r in results:
        by_status.setdefault(r.status, []).append(r)

    sections = []
    for status in ORDER:
        group = by_status.get(status)
        if not group:
            continue
        group.sort(key=lambda r: (-_life(r), r.name))
        sections.append(
            f'<h2>{status.value} &middot; {len(group)} <small>&mdash; {BLURB[status]}</small></h2>'
            + "".join(_card(r) for r in group)
        )
    if not sections:
        sections.append('<p class="empty">No claims marked yet.</p>')

    oldest = max((r.age for r in results if r.age is not None), default=None)
    summary = f"{len(results)} claim(s)"
    if oldest:
        summary += f", the least recently verified {config.format_duration(oldest)} ago"

    stamp = state.to_iso(datetime.now(timezone.utc))
    heading = f"asof &middot; {e(title)}" if title else "asof"
    return f"""<title>asof - {e(title) or 'claims'}</title>
<style>{CSS}</style>
<div class="wrap">
<h1>{heading}</h1>
<p class="sub">Every number in your docs is a claim about a moment that has already
passed. <em>{e(summary)}.</em></p>
{"".join(sections)}
<footer>Generated {e(stamp)} by asof. The bar under each claim shows how much of its
shelf life has been used.</footer>
</div>
"""
