"""A single-file HTML register: every claim, and how much of its life it has used.

Laid out as a ledger rather than a grid of cards, because that is what it is -
one line per claim, read down the left edge, with the things that need somebody
at the top. The bar under each row measures shelf life used, not health, so a
claim can be perfectly true and still be nearly due.
"""

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
    Status.ORPHAN: "the marker is gone, so nothing is watching this",
    Status.SKIPPED: "not re-run this time",
    Status.NEW: "seen for the first time",
    Status.OK: "still true",
}

LABEL = {
    Status.ERROR: "error", Status.INCONSISTENT: "split", Status.DRIFT: "drift",
    Status.STALE: "stale", Status.ORPHAN: "orphan", Status.SKIPPED: "skipped",
    Status.NEW: "new", Status.OK: "verified",
}

TONE = {
    Status.ERROR: "bad", Status.INCONSISTENT: "bad", Status.DRIFT: "bad",
    Status.STALE: "warn", Status.ORPHAN: "warn", Status.SKIPPED: "mute",
    Status.NEW: "mute", Status.OK: "good",
}

FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
         "&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@400;600"
         "&display=swap")

CSS = """
:root{
  --paper:#f2f4f3; --card:#fbfcfc; --rule:#d8dedd; --rule-soft:#e6eae9;
  --ink:#12191c; --ink-soft:#4a5558; --ink-faint:#6f797c;
  --accent:#0f5a5e; --accent-soft:#e3edec;
  --good:#2e6f4e; --warn:#9a6a12; --bad:#a33a2e; --mute:#6f797c;
  --track:#e2e7e6;
  --serif:"IBM Plex Serif",Georgia,"Times New Roman",serif;
  --sans:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#0e1416; --card:#151d20; --rule:#273336; --rule-soft:#1e292c;
    --ink:#e8eeec; --ink-soft:#a6b2b3; --ink-faint:#7d8a8c;
    --accent:#5fbdb4; --accent-soft:#16302f;
    --good:#63b487; --warn:#d2a04c; --bad:#e0796c; --mute:#7d8a8c;
    --track:#222e31;
  }
}
:root[data-theme="dark"]{
  --paper:#0e1416; --card:#151d20; --rule:#273336; --rule-soft:#1e292c;
  --ink:#e8eeec; --ink-soft:#a6b2b3; --ink-faint:#7d8a8c;
  --accent:#5fbdb4; --accent-soft:#16302f;
  --good:#63b487; --warn:#d2a04c; --bad:#e0796c; --mute:#7d8a8c;
  --track:#222e31;
}

*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.sheet{max-width:60rem;margin:0 auto;padding:3.5rem 1.5rem 5rem}

header{border-bottom:2px solid var(--ink);padding-bottom:1.25rem}
.eyebrow{font-family:var(--mono);font-size:.7rem;letter-spacing:.16em;
  text-transform:uppercase;color:var(--accent);margin:0 0 .7rem}
h1{font-family:var(--serif);font-weight:600;font-size:2.1rem;line-height:1.15;
  margin:0;letter-spacing:-.015em;text-wrap:balance}
h1 .repo{color:var(--accent)}
.standfirst{margin:.7rem 0 0;max-width:34rem;color:var(--ink-soft);font-size:.97rem}

.tally{display:flex;flex-wrap:wrap;gap:0;margin:1.5rem 0 0;
  border:1px solid var(--rule);border-radius:3px;background:var(--card);overflow:hidden}
.tally div{flex:1 1 7rem;padding:.7rem .9rem;border-right:1px solid var(--rule-soft)}
.tally div:last-child{border-right:0}
.tally b{display:block;font-family:var(--mono);font-size:1.45rem;font-weight:500;
  line-height:1.1;font-variant-numeric:tabular-nums}
.tally span{font-family:var(--mono);font-size:.68rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-faint)}
.tally .good b{color:var(--good)} .tally .warn b{color:var(--warn)}
.tally .bad b{color:var(--bad)} .tally .mute b{color:var(--ink-soft)}

section{margin-top:2.75rem}
h2{font-size:.72rem;font-family:var(--mono);letter-spacing:.16em;
  text-transform:uppercase;color:var(--ink-faint);font-weight:500;
  margin:0 0 .1rem;display:flex;align-items:baseline;gap:.6rem}
h2 em{font-style:normal;font-family:var(--sans);letter-spacing:0;
  text-transform:none;font-size:.85rem;color:var(--ink-soft)}

.row{display:grid;grid-template-columns:5.5rem minmax(0,1fr) auto;
  gap:.35rem 1rem;align-items:baseline;
  padding:.95rem 0 .85rem;border-bottom:1px solid var(--rule-soft)}
.row:first-of-type{border-top:1px solid var(--rule)}

.chip{font-family:var(--mono);font-size:.66rem;letter-spacing:.1em;
  text-transform:uppercase;padding:.2rem .45rem;border-radius:2px;
  border:1px solid currentColor;justify-self:start;white-space:nowrap}
.chip.good{color:var(--good)} .chip.warn{color:var(--warn)}
.chip.bad{color:var(--bad)} .chip.mute{color:var(--mute)}

.name{font-weight:600;font-size:1rem;word-break:break-word}
.value{font-family:var(--mono);font-size:1rem;font-variant-numeric:tabular-nums;
  text-align:right;white-space:nowrap}
.value .was{color:var(--ink-faint);text-decoration:line-through;margin-right:.4rem}
.value .now{color:var(--bad)}

.detail{grid-column:2/4;display:flex;flex-direction:column;gap:.3rem;min-width:0}
.why{color:var(--ink-soft);font-size:.9rem;max-width:44rem}
.note{font-size:.88rem;color:var(--bad)}
.row.warn .note{color:var(--warn)}
.where{font-family:var(--mono);font-size:.76rem;color:var(--ink-faint);
  overflow-x:auto;white-space:nowrap;padding-bottom:.1rem}

.life{grid-column:2/4;display:flex;align-items:center;gap:.6rem;margin-top:.15rem}
.meter{flex:1;height:3px;background:var(--track);border-radius:2px;overflow:hidden;
  max-width:22rem}
.meter i{display:block;height:100%;min-width:2px;border-radius:2px;background:var(--good)}
.life.warn .meter i{background:var(--warn)} .life.bad .meter i{background:var(--bad)}
.life small{font-family:var(--mono);font-size:.7rem;color:var(--ink-faint);
  font-variant-numeric:tabular-nums}

.empty{border:1px dashed var(--rule);border-radius:3px;padding:2.5rem 1.5rem;
  text-align:center;color:var(--ink-soft)}
.empty code{font-family:var(--mono);font-size:.85rem;color:var(--accent);
  background:var(--accent-soft);padding:.15rem .4rem;border-radius:2px}

footer{margin-top:3.5rem;padding-top:1.1rem;border-top:1px solid var(--rule);
  color:var(--ink-faint);font-size:.82rem;display:flex;flex-wrap:wrap;
  gap:.4rem 1.25rem;justify-content:space-between}
footer code{font-family:var(--mono)}

@media (max-width:34rem){
  .row{grid-template-columns:1fr auto}
  .chip{grid-column:1/3;margin-bottom:.15rem}
  .detail,.life{grid-column:1/3}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def _life(result: Result) -> float | None:
    """How much of the claim's shelf life has been used, or None if it has none."""
    if not result.claim.every or result.age is None:
        return None
    return max(0.0, result.age / result.claim.every)


def _row(result: Result) -> str:
    e = html.escape
    tone = TONE[result.status]
    parts = [f'<div class="row {tone}">',
             f'<span class="chip {tone}">{LABEL[result.status]}</span>',
             f'<span class="name">{e(result.name)}</span>']

    if result.status is Status.DRIFT and result.produced:
        parts.append(f'<span class="value"><span class="was">{e(result.document)}</span>'
                     f'<span class="now">{e(result.produced)}</span></span>')
    else:
        parts.append(f'<span class="value">{e(result.document) or "&mdash;"}</span>')

    detail = []
    if result.claim.why:
        detail.append(f'<span class="why">{e(result.claim.why)}</span>')
    if result.message and result.status is not Status.OK:
        detail.append(f'<span class="note">{e(result.message)}</span>')
    if result.markers:
        where = ", ".join(m.where for m in result.markers)
        detail.append(f'<span class="where">{e(where)}</span>')
    if detail:
        parts.append(f'<div class="detail">{"".join(detail)}</div>')

    life = _life(result)
    if life is not None:
        tone = "bad" if life >= 1 else "warn" if life >= 0.7 else "good"
        span = config.format_duration(result.claim.every)
        used = config.format_duration(result.age) if result.age else "0s"
        parts.append(
            f'<div class="life {tone}"><span class="meter">'
            f'<i style="width:{min(life, 1.0) * 100:.1f}%"></i></span>'
            f'<small>{e(used)} of {e(span)}</small></div>')

    parts.append("</div>")
    return "".join(parts)


def _tally(results: list[Result]) -> str:
    counts: dict[Status, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    cells = []
    for status in ORDER:
        if counts.get(status):
            cells.append(f'<div class="{TONE[status]}"><b>{counts[status]}</b>'
                         f'<span>{LABEL[status]}</span></div>')
    return f'<div class="tally">{"".join(cells)}</div>' if cells else ""


def render(results: list[Result], title: str = "") -> str:
    e = html.escape
    by_status: dict[Status, list[Result]] = {}
    for result in results:
        by_status.setdefault(result.status, []).append(result)

    sections = []
    for status in ORDER:
        group = by_status.get(status)
        if not group:
            continue
        group.sort(key=lambda r: (-(_life(r) or 0), r.name))
        sections.append(
            f'<section><h2>{LABEL[status]} &middot; {len(group)}'
            f'<em>{BLURB[status]}</em></h2>{"".join(_row(r) for r in group)}</section>')

    if not sections:
        sections.append(
            '<section><div class="empty"><p>No claims marked yet.</p>'
            '<p>Write <code>&lt;!-- asof:integrations --&gt;</code> after a number '
            'in a document, then run <code>asof init</code>.</p></div></section>')

    oldest = max((r.age for r in results if r.age is not None), default=None)
    standing = f"{len(results)} claim{'' if len(results) == 1 else 's'} on the books"
    if oldest:
        standing += f", the least recently verified {config.format_duration(oldest)} ago"

    stamp = state.to_iso(datetime.now(timezone.utc))
    name = e(title) if title else "this repository"

    return f"""<title>{f"{e(title)} " if title else ""}Claims Register</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<style>{CSS}</style>
<div class="sheet">
<header>
  <p class="eyebrow">asof &middot; claims register</p>
  <h1>Every number in <span class="repo">{name}</span> that is a claim about a
  moment already past</h1>
  <p class="standfirst">{e(standing)}. Each one either carries a command that
  reproduces it, or a date by which somebody has to look again.</p>
  {_tally(results)}
</header>
{"".join(sections)}
<footer>
  <span>Generated <code>{e(stamp)}</code></span>
  <span>The bar measures shelf life used, not health &mdash; a claim can be
  true and still be nearly due.</span>
</footer>
</div>
"""
