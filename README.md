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
git clone https://github.com/Blueangelman36/asof
pip install -e asof          # or run it in place: python -m asof
```

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
                                     fix with: asof update p99-latency
  STALE  enterprise-customers  12    docs/sales.md:9
                                     last verified 114d ago, wanted every 90d

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
| `ORPHAN` | configured, but no longer written anywhere |

`SPLIT` is the one people are surprised by. Mark the same name in the README, the
landing page and the pitch deck, and `asof` will tell you the day they stop agreeing
with each other — which is usually the day someone updated one of the three.

## In CI

```yaml
- run: pip install asof
- run: asof check --fail-on drift,inconsistent,error   # what a machine can settle
- run: asof check --no-run --fail-on stale             # what a person must settle
```

Splitting it in two is deliberate. The first command is a build failure: a number in
your docs is provably wrong. The second is a reminder, and is usually better as a
scheduled job that opens an issue than as something that blocks a merge.

For a number whose command only runs somewhere with credentials, `asof check --no-run`
judges it by age alone and never executes anything.

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
- **Formatting is not drift.** `1,247`, `1247` and `1.247k` are the same claim.
  Units are not: `250ms` will never match `250s`.
- **`run` commands are shell commands from your own repo**, executed by `asof check`.
  That is the same trust you already extend to a Makefile, but it is worth saying out
  loud before you run `asof check` inside a pull request from a stranger.

## This repo, checked by itself

The README you are reading is under `asof`, which is the only honest way to ship this:

- The whole tool is 1,985 lines of Python. <!-- asof:source-lines -->
- It is covered by 85 tests. <!-- asof:test-count -->
- It has 0 third-party dependencies. <!-- asof:dependencies -->

Those three numbers are checked on every push by [the workflow](.github/workflows/ci.yml).
If you are reading this on a commit where CI is green, they are true as of that commit.

## Licence

MIT.
