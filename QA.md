# QA

A tool that tells you when your numbers stopped being true has no business
stating numbers of its own on trust. So this report is marked up with `asof`
and checked by CI along with everything else: the numbers below either carry a
command that reproduces them, or carry a date by which somebody has to look
again.

## What was run

- **The test suite**: 287 tests. <!-- asof:test-count -->
- **An adversarial sweep** (`qa/sweep.py`): 56 hostile-input probes <!-- asof:qa-probes -->
  over encodings, malformed markers, broken config, damaged lockfiles, runaway
  commands and numbers that are not numbers, plus 17 invariants <!-- asof:qa-invariants -->
  asserted across them.
- **A packaging check**: `pip install` into a clean virtualenv, then the
  installed `asof` console script run against four real repositories.
- **A performance check** on a synthetic tree of several hundred files.
- **A clean-room run**: installed straight from the pushed repository into an
  empty virtualenv, pointed at an Android project that had never been marked,
  and taken through the whole adoption loop with the installed binary.

The sweep asks a different question from the tests. The tests say what `asof`
should do, one case at a time. The sweep says what it must never do — never
raise a traceback, never exit 0 on a broken repo, never let a read-only command
write a file — across every input at once.

```bash
python -m unittest discover -s tests -t .
python qa/sweep.py
```

## What it found

Ten defects, all now fixed and pinned by tests.

**A number could bind silently to the wrong value.** Kotlin, Python, Rust and
Java group thousands with underscores, and `18_000` parsed as `18` followed by
`000` — so a marker on that line would have claimed **0** and compared it, in
earnest, against the 18,000 in the README. Not a crash: a confident wrong
answer, which is the worst kind of bug for a tool whose entire job is to be
trusted about numbers. Found by the clean-room run, on the first real file it
touched.

**The timeout was a message, not a limit.** `timeout = 1` against a command
that sleeps for thirty seconds returned after thirty seconds, while reporting
that it had timed out after one. `shell=True` means the child is a shell and
the real work is its grandchild; killing the shell orphaned the grandchild,
which kept the pipes open, so the read that followed blocked until it felt like
finishing. A claim command could hang CI indefinitely. It now kills the process
group and returns in 1.2s. <!-- asof:timeout-bug -->

**Seven ways to get a traceback instead of a sentence.** A typo in `asof.ini` —
an unreadable duration, tolerance or timeout, a file that was not INI at all, a
duplicated section — crashed with a Python stack trace. So did a lockfile
containing a JSON list, and asking for a report inside a folder that did not
exist. Configuration errors now name the file, line, section and key, and exit
2.

**Two ways to fail open.** `asof check tyop` — a claim name matching nothing —
printed "no claims yet" and exited 0, so a typo in a CI invocation would pass
forever. And the lockfile churned: every run rewrote every timestamp, which
left the working tree permanently dirty and put a meaningless diff in every
commit. Confirmations are now recorded at hour granularity, which is invisible
to staleness thresholds measured in days and removes the churn entirely.

**A range dash read as a minus sign.** "restricted to 50-99%" parsed as `50`
and `-99%`. Found by a test I wrote for something else, which is the usual way.

## What the fixes are worth

The sweep's own precision improved while this ran. On `calibration-ledger`, a
single-file web app, `asof suggest` proposed 166 candidate numbers <!-- asof:suggest-before -->
topped by `30px` — it was mining the stylesheet. In HTML, code is not speech
any more than it is in Markdown, so `<style>` and `<script>` bodies are now
skipped when *discovering* candidates, and layout units are never claims. That
left 18 candidates, <!-- asof:suggest-after --> topped by the one claim I had
picked by hand on that repo a day earlier.

A marker somebody deliberately wrote inside a `<script>` still works. Discovery
is a guess; a marker is a decision, and the two deserve different treatment.

## What is still true and worth knowing

- **Scanning is I/O-bound.** Roughly a second for 640 files, of which about a
  tenth is actual work and the rest is reading them. A very large monorepo
  should expect this to scale with file count, not with cleverness.
- **`asof` runs shell commands from the repo it is pointed at.** That is the
  same trust a Makefile asks for, but a pull request from a stranger can edit
  `asof.ini`, so `asof check` on untrusted branches deserves the same care as
  any other build step.
- **The suggester is a heuristic and says so.** It ranks by repetition, which
  means it finds constants stated twice and misses a number stated once and
  never repeated. Those still need a person to notice them.
- **Windows and POSIX are both tested in CI**, on the oldest and newest
  supported Python.

## The claims in this document

`test-count`, `qa-probes` and `qa-invariants` are re-derived on every push by
`tools/facts.py`. The three narrative numbers — the timeout figure and the two
suggester counts — were measured by hand against an external repository that CI
does not clone, so they carry a shelf life instead of a command, and `asof`
will ask somebody to re-measure them when it expires.

That is the whole argument of this project, applied to the document that makes
it: a number is either reproducible or it is somebody's job.
