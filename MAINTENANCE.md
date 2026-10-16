# Maintaining this profile

The profile uses GitHub's own typography and light/dark themes. Its short navigation
and restrained layout take inspiration from [Anthony Fu's profile](https://github.com/antfu).
The content and contribution renderer are written for this profile; no third-party
profile assets, tracking badges, or remotely hosted statistics cards are required.

## What gets listed

The updater walks the complete paginated list of merged pull requests authored by
`Avaivartika`. It keeps public contributions to other owners' non-fork repositories.
Private repositories, personal projects, open or unmerged PRs, and other authors'
work are excluded before anything is written to disk.

This is a list of merged PR contributions. Direct commits, issue reports, and code
reviews are not inferred from it. GitHub's profile activity provides that broader view.

Each project appears once on the profile. Its most recent merged PR is shown, and
every merged PR is retained in [CONTRIBUTIONS.md](CONTRIBUTIONS.md). The machine-readable
record is [data/contributions.json](data/contributions.json).

## Edit the profile

Edit the introduction and navigation directly in `README.md`. The updater only
replaces the section between `CONTRIBUTIONS:START` and `CONTRIBUTIONS:END`.

To give a project a friendlier name, description, or a summary of a specific PR,
edit `profile.json`. A new project needs no manual entry; it initially uses the
upstream repository name, description, and PR title.

## Update locally

Python 3.10 or newer and an authenticated GitHub CLI are sufficient. There are no
third-party Python dependencies. Alternatively, provide `GH_TOKEN` as an environment
variable. Never place a token in a file in this repository.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/update_contributions.py
python3 scripts/update_contributions.py --offline --check
```

The updater fails without replacing the published list if GitHub reports an error,
pagination is incomplete, or a previously recorded contribution disappears. Review
upstream deletions or visibility changes and then use `--allow-removals` when appropriate.
When a repository becomes private, remove its public entry promptly with that flag.

## Scheduled updates

The workflow in `.github/workflows/update-contributions.yml` checks once a day at
01:17 UTC, or 09:17 in Shanghai. It also supports **Actions → Update contributions →
Run workflow** and runs when its source files change. Its built-in `GITHUB_TOKEN`
reads public contribution metadata and writes only to this profile repository.
The publisher uses the GitHub Actions bot identity and only commits when content changes.

GitHub can delay scheduled jobs and disables scheduled workflows after 60 days
without repository activity. If that happens, re-enable **Update contributions** in
the Actions tab and run it manually. No empty commits are made to keep a schedule alive.

Publishing or changing the workflow requires the GitHub CLI login to include the
`workflow` OAuth scope. If it does not, run `gh auth refresh -h github.com -s workflow`
and complete GitHub's browser authorization. The updater itself does not require
that extra scope when it runs inside GitHub Actions.
