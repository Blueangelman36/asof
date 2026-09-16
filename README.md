# asof

*Every number in your docs is a claim about a moment that has already passed.*

Your README says the service handles 10k requests a second. Your pricing page says
47 integrations. Your onboarding doc says 12 enterprise customers. Each of those was
true on the day it was typed, and prose has no test suite, so none of them will ever
fail. They just quietly stop being true, and the person who finds out is a customer.

`asof` keeps the evidence next to the claim. A number can carry the command that
produced it, and gets re-established every time CI runs. A number no command can
produce — the ones that rot worst — carries a shelf life instead, and `asof` asks
someone to look again when it expires.

## Try it

No dependencies. Python 3.10+.

```bash
pip install git+https://github.com/Blueangelman36/asof
```

Or take the single file and skip installing anything: `python asof.pyz check`
works from a bare interpreter with no virtualenv and no network.

### Adopting it on a repo that has none of this

`asof suggest` reads your documents and tells you which numbers look like claims
somebody will forget to update, worst first:

```text
$ asof suggest
24 unclaimed number(s) in your documents. The ones written in more than one place
come first, because those are already two people's job to remember:

  2.5 kHz      README.md:310
               tolerance (default ±2.5 kHz) because receivers drift with temperature
               same number at aliases.example.toml:10, voice/aliases.py:37
               paste after it:  <!-- asof:tolerance-default -->

  8420         README.md:64
               Dashboard at <http://127.0.0.1:8420>.
               same number at config.pi.toml:30, config.toml:6, dashboard/server.py:8
               paste after it:  <!-- asof:dashboard-http -->
```

The ranking is one idea: **a number written in a document and again in a config file
is a constant stated twice by two people who will not both remember to change it.**
That is the shape of claim worth catching, and it takes a count rather than a
judgement. Round numbers are discounted — 50 and 100 and 24 are in every stylesheet
ever written, so sharing one means nothing — and a value that turns up in eight files
is a constant of the codebase, not a claim about it. Add `--why` to see the reasoning
for each, and `--json` to pipe it somewhere.

The name it proposes is a guess from the surrounding words, meant to be edited. When
there is no real word to use it says `NAME` rather than inventing one.

### Marking a number

Mark a number by writing `asof:NAME` in whatever passes for a comment in that file.
The marker claims the last value on the line before it:

```markdown
We support 47 integrations.          <!-- asof:integrations -->
```

```yaml
replicas: 12    # asof:prod-replicas
```

```python
TIMEOUT_MS = 250    # asof:p99-latency
```

Then say where each number comes from, in `asof.ini`:

```ini
[integrations]
run = ls integrations/*.py | wc -l
why = What we can actually connect to on the day you read this.

[p99-latency]
run = ./bench.sh --p99
tolerance = 10%
why = Median of five runs on the CI box. Noisy below 10%.

[enterprise-customers]
every = 90d
owner = @sales
why = No system of record. Ask Sales and change the number by hand.
```

And check them:

```text
$ asof check
  ok     integrations          47    README.md:14
  DRIFT  p99-latency           250   docs/perf.md:31
                                     document says 250, command says 312ms
                                     -> run `asof update p99-latency` to take the
                                        command's answer
  STALE  enterprise-customers  12    docs/sales.md:9
                                     last verified 114d ago, wanted every 90d
                                     -> check it by hand, then `asof touch
                                        enterprise-customers`

3 claim(s): 1 drift, 1 ok, 1 stale
```

`asof check` exits non-zero when something has rotted, so it belongs in CI next to
your tests. `asof update` rewrites the drifting numbers for you, in the style they
were already written in — `1,247` becomes `1,389`, and `10.4k` becomes `12.4k`. It
rounds to the precision the document used, but never past it: a document saying `3.9`
and a command printing `3.10` is rewritten to `3.10`, because dropping that zero
would change which Python it means.

## The two kinds of claim

**Numbers a machine can answer** get a `run` command. The last line of its output is
the truth. These can never be wrong for long, because CI re-establishes them on every
push.

**Numbers only a person can answer** get an `every` instead. Nobody can automate
"how many enterprise customers do we have" in a repo that has no CRM, so `asof` does
not pretend to. It just remembers when someone last stood behind the number, and says
so when that was too long ago:

```bash
asof touch enterprise-customers   # I checked. It is still right.
```

Editing the number by hand counts as checking it, so the ordinary workflow — change
the doc, commit — resets the clock on its own.

## What it catches

| | |
|---|---|
| `DRIFT` | the document and the command disagree |
| `STALE` | nobody has stood behind this in too long |
| `SPLIT` | the same claim, two different numbers in two files |
| `ERROR` | the command would not run |
| `ORPHAN` | every marker for a claim is gone, so nobody is watching that number |
| `DROPPED` | one file that used to carry a claim no longer does |

`SPLIT` is the one people are surprised by, and the one that needs no command at all.
Mark the same name in the README, in `config.toml` and in the Raspberry Pi profile,
and `asof` tells you the day the three stop agreeing — which is usually the day
somebody updated one of them. It compares across notation too, so a README saying
`±2.5 kHz` stays tied to a config saying `tolerance_hz = 2500`, and prose saying
`99%` stays tied to an HTML slider saying `max="99"`.

`ORPHAN` and `DROPPED` fail the build by default, and that is the deliberate part.
Someone edits a sentence, the marker goes with it, and the number silently stops being
checked — a guard that stays green when its own markers disappear is worse than no
guard, because you think you have one. `DROPPED` is the subtler half: a claim marked in
a README and three config files keeps passing if one file loses its marker, since the
survivors still agree. So the lockfile records which files carried each claim, and
losing one is reported by name. `asof touch NAME` accepts the removal when it was
deliberate.

Only `DRIFT` has a right answer to write, so `asof update` fixes those and tells you
plainly what it left behind. Nothing else is safely automatable: when two files
disagree, only a person knows which one is wrong.

## In CI

```yaml
- run: pip install git+https://github.com/Blueangelman36/asof
- run: asof check                            # what a machine can settle
- run: asof check --no-run --fail-on stale   # what a person must settle
```

Splitting it in two is deliberate. The first command is a build failure: a number in
your docs is provably wrong. The second is a reminder, and is usually better as a
scheduled job that opens an issue than as something that blocks a merge.

For a number whose command only runs somewhere with credentials, `asof check --no-run`
judges it by age alone and never executes anything.

### Exit codes

Written down as a contract, so a CI step, a hook or an agent can rely on it:

| Code | Meaning |
|---|---|
| `0` | nothing to say — every claim in scope holds |
| `1` | something is blocking: a number is wrong, or nobody has stood behind it |
| `2` | asof could not do its job: a claim's command would not run, or asof itself was used wrong (bad flag, unknown claim name, unreadable `asof.ini`) |

`2` covers both halves of "could not do its job", because from CI's point of view a
command that will not run and a config that will not parse are the same event: asof
reached no verdict, and a green build would be a lie either way.

The two halves differ in one respect worth knowing. `--fail-on` governs the first —
`asof check --fail-on none` exits `0` even when a claim's command is broken, which is
what you want on a branch where that command cannot run. It does not govern the
second: a bad flag or an unreadable `asof.ini` exits `2` whatever `--fail-on` says,
since asof never got as far as having statuses to filter.

## For coding agents

An agent almost never meets a tool by reading its README. It meets one when CI
goes red on a change it just made, and whatever that log says is the only
documentation it gets. So every failure names its own next step:

```text
  SPLIT  dashboard-port  8420  README.md:64 (+3)
                         one claim, several numbers: 8420 at README.md:64, 8500 at config.pi.toml:30
                         -> make these agree - edit whichever is wrong, and keep
                            the `asof:dashboard-port` comment on each line
```

That line is in `asof check --json` too, as a `remedy` field on every failure,
so an agent can act on it without parsing prose.

### One JSON shape

Every command that reports anything — `check`, `list`, `suggest`, `why`, `update`
and `touch` — returns the same envelope, so a caller learns it once:

```json
{
  "tool": "asof",
  "version": "0.2.0",
  "checked": 8,
  "blocked": true,
  "counts": { "ok": 6, "inconsistent": 1, "stale": 1 },
  "items": [
    {
      "id": "dashboard-port",
      "status": "inconsistent",
      "where": { "path": "README.md", "line": 64 },
      "why": "README prose and config.toml each name this port independently.",
      "detail": "one claim, several numbers: 8420 at README.md:64, 8500 at config.toml:6",
      "remedy": "make these agree - edit whichever is wrong, and keep the `asof:dashboard-port` comment on each line"
    }
  ]
}
```

The outer keys are deliberately generic, and each item leads with `id`,
`status`, `where` and `why`. The two commands that *change* things say so in the
same shape: `update --json` gives each item a `changed` flag and an `edits` list
of `{path, line, from, to}`, and sets `dry_run` on the envelope, so a caller can
see exactly which bytes moved — or would have. `touch --json` marks each item
`touched`, and reports a name it could not find as `status: "unknown"` rather
than only on stderr. Anything specific to `asof` — `value`, `produced`,
`settled_by`, `every_seconds`, every `locations` entry — rides alongside those
rather than in place of them, so a caller that only knows the common keys still
works. `blocked` is the exit code in boolean form: true means this run should
stop a build.

### Asking about one claim

```text
$ asof why dashboard-port
dashboard-port   8420

  README prose and config.toml each name this port independently. If they
  disagree, the ssh tunnel line in the deployment notes is wrong.

  settled   by hand, every 180d
  owner     @platform
  last      verified 12d ago - due in 168d
  marked    README.md:64, config.toml:6
```

`why` is the question somebody actually has when they meet an unfamiliar marker
in a line they were editing. It runs no commands and writes nothing — `check` is
where verdicts come from — so it is always safe to ask.

Two more things make the difference between a tool agents trip over and one
they use:

```bash
asof skill                      # installs the Claude Code skill into this repo
asof agents >> AGENTS.md        # the behavioural rules, for the file agents read
python tools/build_pyz.py       # dist/asof.pyz - the whole tool in one 80 KB file
```

`asof skill` writes `.claude/skills/asof/SKILL.md`, which Claude Code loads when a
request touches this ground — a failing check, adopting `asof`, or changing a
constant that a document might also state. That last trigger is the useful one:
it arrives *before* the mistake rather than after CI catches it. The skill ships
inside the package, so the copy you read on GitHub and the copy `pip` installs
are asserted to be the same file.

`asof agents` writes the instructions in the form an agent needs them: change
marked numbers freely, check before changing a constant that a document also
states, and **never delete an `asof:` comment to make a check pass.** That last
rule matters more than the rest put together — deleting the marker is the
shortest path to a green build, and it is exactly the failure `asof` exists to
prevent. Orphaned claims fail the build by default for the same reason.

The single-file build is for repositories that will not take a dependency.
It is stdlib-only, so the whole tool fits in a zipapp: commit `asof.pyz`, run
`python asof.pyz check`, no install step and no network.

`asof agents` prints the asof half only. If the repository runs other checks of this
kind, merge them under one heading rather than letting each tool append its own — two
competing sets of instructions about what to run before changing something is worse
for an agent than one set that is slightly generic:

```markdown
## Before you change things

- `asof check` — which numbers in the docs are no longer true
- `<your other check>` — …

If a check blocks you, its output names the next step. Do not silence a check to
make the build green.
```

## The lockfile

`asof.lock` records, for every claim, the value and the moment it was last known to be
true. Commit it. A number changing is one diff; the moment somebody stood behind it is
another, and you want both in the history.

## The report

```bash
asof report -o asof.html
```

A single self-contained page listing every claim with a bar showing how much of its
shelf life it has used. Useful as a quarterly "what do we still believe" review.

## Details worth knowing

- **In Markdown, code is not speech.** Markers inside fenced blocks and inside
  `` `code spans` `` are skipped, because a document that *explains* `asof` is full of
  example markers and none of them are claims about that document. This page is the
  proof: everything above is an example, and only the three numbers below are claims.
  Set `fenced = yes` under `[asof]` to scan fenced blocks anyway. A number in
  backticks is still a number — only the marker has to be out in the open.
- **`asof:off` anywhere a marker would be heard** excludes the whole file.
- **`asof:NAME>`** (with a trailing `>`) binds the first value *after* the marker,
  for files where the comment has to come first.
- **On a crowded line, put the marker right after the value you mean.** A marker
  takes the *last* value before it, so at the end of
  `<input min="50" max="99" step="1" value="70">` it claims the `70`. Two claims can
  share a line the same way: `20<!-- asof:per-hour --> calls/hour,
  200<!-- asof:per-day -->/day`.
- **Formatting is not drift.** `1,247`, `1247` and `1.247k` are the same claim, and
  so are `2.5 kHz` in prose and `2500` in a config file. Units are not: `250ms` will
  never match `250s`.
- **A version is one value, and compares as a version.** `v3.10.0`, `"3.10.0"` and
  `3.10` are the same release; `2.4.1-rc.2` is not `2.4.1`, and an update keeps
  whichever `v` and quotes the document already had. asof recognises a version by
  its shape — a `v` in front, a third component, or a pre-release tag — because a
  bare `3.10` is also the decimal 3.1, and nothing in the text says which the
  author meant. For a claim written that way, say so:

  ```ini
  [python-floor]
  type = version       # so 3.10 and 3.1 are different Pythons, not one number
  ```
- **A quoted number is a number.** Config files quote what prose writes bare, so a
  README saying `99%` still matches `max="99"` in HTML or `version = "3.11"` in TOML.
  A quoted *word* stays a word, so `"low"` is a claim you can make about a setting.
- **A unit may follow a space** — `2.5 kHz`, `250 ms`, `1.2 GB` — but only for units
  on a known list. Otherwise "47 integrations" would read as 47 *integrations*, and
  every noun in your docs would become a unit.
- **`run` commands are shell commands from your own repo**, executed by `asof check`.
  That is the same trust you already extend to a Makefile, but it is worth saying out
  loud before you run `asof check` inside a pull request from a stranger.

## What this does not cover

`asof` guards **claims about** a system — numbers in documents and configs, each
re-established by a command or given a shelf life. It has nothing to say about
**reasons for** a system: why a retry loop is there, why that `sleep(50)` is not a
mistake, why the `if` that can't happen is checked anyway. Those go stale too, and
by a different mechanism — nobody deletes a number by accident, but people delete
strange-looking code all the time.

That is a separate job, and deliberately a separate program. A claim that can expire
and a reason that can be forgotten are not the same thing, and one tool that did both
would explain itself worse than two that each answer "what does this do?" in a
sentence.

They do meet in one place, which is worth knowing about even though nothing is built
for it yet: **a reason usually contains a claim.** "The vendor rate-limits at 200
requests a minute, so the batch size is 180" is a number that will stop being true,
sitting in the one place nobody thinks to re-check. Recording a reason and never
questioning it again is exactly the optimism `asof` exists to refuse. If a repository
using both ever wants that closed, the shape is for `asof` to read recorded reasons
as another document source — but today it does not, and nothing here should be read
as though it did.

## This repo, checked by itself

The README you are reading is under `asof`, which is the only honest way to ship this:

- The whole tool is 5,172 lines of Python. <!-- asof:source-lines -->
- It is covered by 295 tests. <!-- asof:test-count -->
- It has 0 third-party dependencies. <!-- asof:dependencies -->

Those three numbers are checked on every push by [the workflow](.github/workflows/ci.yml).
If you are reading this on a commit where CI is green, they are true as of that commit.

## Licence

MIT.
