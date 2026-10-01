# Releasing

A tag produces a GitHub release with `asof.pyz` attached, and — once the setup below is
done — the package on PyPI. Both come from `.github/workflows/release.yml`.

## The name on PyPI

`asof` on PyPI belongs to an unrelated project, so the distribution is published as
**`asof-claims`**. The command it installs is still `asof`, the same way chesterton ships
as `chesterton` and installs `fence`. If you would rather another name, change `name` in
`pyproject.toml` before the first release: the first upload claims a name permanently.

## One-time setup

1. A PyPI account with 2FA enabled.
2. On PyPI: **Your projects → Publishing → Add a new pending publisher**

   | Field | Value |
   | --- | --- |
   | PyPI project name | `asof-claims` |
   | Owner | `Blueangelman36` |
   | Repository | `asof` |
   | Workflow | `release.yml` |
   | Environment | `pypi` |

3. In this repository: **Settings → Environments → New environment → `pypi`**. Adding
   yourself as a required reviewer there means a release waits for your approval even
   after the tag is pushed.

No API token is created or stored; the workflow authenticates with a short-lived OIDC
token only it can obtain.

## Releasing

```bash
# 1. Set the version in both places. The workflow refuses a tag that disagrees.
$EDITOR pyproject.toml asof/__init__.py

# 2. Commit, then tag the commit on main.
git tag -a v0.3.2 -m "asof 0.3.2"
git push origin v0.3.2
```

Then watch the run in the **Actions** tab. The GitHub release appears when the build
passes; the PyPI job waits on the `pypi` environment.

## Afterwards

Other repositories should pin what they use, whichever way they use it:

```yaml
- uses: Blueangelman36/asof@v0.3.2          # the action
- run: pip install asof-claims==0.3.2        # from PyPI
- run: pip install git+https://github.com/Blueangelman36/asof@v0.3.2
```

A version on PyPI can be yanked but never deleted or reused, so a broken release gets a
new number rather than a replacement.
