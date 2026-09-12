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
were already written in — `1,247` becomes `1,389`, and `10.4k` becomes `12.4k`.

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
| `ORPHAN` | a marker was deleted, so nobody is watching that number now |

`SPLIT` is the one people are surprised by, and the one that needs no command at all.
Mark the same name in the README, in `config.toml` and in the Raspberry Pi profile,
and `asof` tells you the day the three stop agreeing — which is usually the day
somebody updated one of them. It compares across notation too, so a README saying
`±2.5 kHz` stays tied to a config saying `tolerance_hz = 2500`, and prose saying
`99%` stays tied to an HTML slider saying `max="99"`.

`ORPHAN` fails the build by default, and that is the deliberate part. Someone edits a
sentence, the marker goes with it, and the number silently stops being checked — a
guard that stays green when its own markers disappear is worse than no guard, because
you think you have one.

Only `DRIFT` has a right answer to write, so `asof update` fixes those and tells you
plainly what it left behind. Nothing else is safely automatable: when two files
disagree, only a person knows which one is wrong.

## In CI

```yaml
- run: pip install asof
- run: asof check                            # what a machine can settle
- run: asof check --no-run --fail-on stale   # what a person must settle
```

Splitting it in two is deliberate. The first command is a build failure: a number in
your docs is provably wrong. The second is a reminder, and is usually better as a
scheduled job that opens an issue than as something that blocks a merge.

For a number whose command only runs somewhere with credentials, `asof check --no-run`
judges it by age alone and never executes anything.

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
- **A quoted number is a number.** Config files quote what prose writes bare, so a
  README saying `99%` still matches `max="99"` in HTML or `version = "3.11"` in TOML.
  A quoted *word* stays a word, so `"low"` is a claim you can make about a setting.
- **A unit may follow a space** — `2.5 kHz`, `250 ms`, `1.2 GB` — but only for units
  on a known list. Otherwise "47 integrations" would read as 47 *integrations*, and
  every noun in your docs would become a unit.
- **`run` commands are shell commands from your own repo**, executed by `asof check`.
  That is the same trust you already extend to a Makefile, but it is worth saying out
  loud before you run `asof check` inside a pull request from a stranger.

## This repo, checked by itself

The README you are reading is under `asof`, which is the only honest way to ship this:

- The whole tool is 4,265 lines of Python. <!-- asof:source-lines -->
- It is covered by 214 tests. <!-- asof:test-count -->
- It has 0 third-party dependencies. <!-- asof:dependencies -->

Those three numbers are checked on every push by [the workflow](.github/workflows/ci.yml).
If you are reading this on a commit where CI is green, they are true as of that commit.

## Licence

MIT.
