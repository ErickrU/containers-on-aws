# Contributing

This repository is a book with a runnable system inside it. Contributions are welcome when they
make a statement more precise, a lab more faithful, or a runbook more useful under pressure. The
bar is the one in [`docs/STYLE_GUIDE.md`](docs/STYLE_GUIDE.md): mechanism before rule, primary
sources, real commands, and the failure path next to the happy path.

## Before you start

- Read [`docs/STYLE_GUIDE.md`](docs/STYLE_GUIDE.md) (templates, voice, rules) and
  [`docs/MANIFEST.md`](docs/MANIFEST.md) (which document owns which topic). A topic lives in exactly
  one place; everything else links there.
- Check [`docs/FACTS-2026-09.md`](docs/FACTS-2026-09.md) for anything time-sensitive. If you have a
  newer verified fact, update the facts sheet in the same change and cite the primary source.
- Open an issue for new documents or structural changes; small corrections can go straight to a
  pull request.

## Set up the checks

```bash
python3 -m venv .venv && .venv/bin/pip install pyyaml cfn-lint      # docs checker + CloudFormation lint
brew install kubeconform kustomize shellcheck                        # or your platform's equivalents
make check                                                           # must print ALL CHECKS PASSED
```

`make check` runs `tools/check.sh`:

| Check | Tool | What fails it |
| --- | --- | --- |
| Heading structure | `tools/check_docs.py` | a `hub/*/L*.md` without exactly the eleven numbered H2 sections in order, or without a `**Level:**` line |
| Links | `tools/check_docs.py` | any relative link to a file that does not exist (anchors are not checked) |
| Language | `tools/check_docs.py` | `master`, `slave`, `whitelist`, `blacklist`, `whiteday`, `blackday` anywhere; 12-digit numbers other than `123456789012` / `000000000000` (digit runs inside hex strings are ignored) <!-- term-ok --> |
| YAML / JSON | `tools/check_docs.py` | anything that does not parse (CloudFormation intrinsics are allowed) |
| CloudFormation | `cfn-lint` | `labs/ecs/cloudformation/*.yaml`, `labs/pipelines/codepipeline/*.yaml` |
| Kubernetes | `kubeconform -strict` with the datreeio CRD catalog | `labs/eks/manifests`, `labs/eks/gitops`, `labs/eks/cluster` (rendered overlays should also pass: `kustomize build labs/eks/manifests/overlays/dev \| kubeconform ...`) |
| Shell | `shellcheck` | every `*.sh` |

When a third-party API forces a word the language check rejects (a Kafka setting, an Argo CD field,
a git branch name), quote it as code and add `<!-- term-ok -->` to that Markdown line or `# term-ok`
to that code line. Do not add the marker to prose.

Additional local checks that are not in `make check` but are expected for the relevant files:
`docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:1.7.12 labs/pipelines/github-actions/*.yml`
for workflows, `hadolint` for Dockerfiles, and the unit tests of any app you touch (see each
`labs/apps/*/README.md`). `make up && make smoke && make down` must still pass after any change to
`labs/apps` or `labs/local`.

## Adding or changing a hub document

1. Find the owner row in `docs/MANIFEST.md`. If the topic has no owner, propose one in the issue and
   add the row.
2. Use the template in `docs/STYLE_GUIDE.md` §3 verbatim: title line, `**Level:**` line, "After
   this document you can", then the eleven sections. The validator is strict about the H2 text.
3. Stay in the length budget for the level (L100 200–350 lines, L200 300–550, L300/L400 400–750);
   tables and diagrams may push past it, prose padding may not.
4. Every level answers the same seven questions (why/why not, interactions, failures, signals,
   testing, DR, Well-Architected). If you cannot fill a section honestly, the topic may belong at a
   different level.
5. Link the matching runbook from §6 and the metrics catalog from §7; add rows to
   `reference/metrics-catalog.md` for any metric you introduce.
6. Sources (§11) are primary documentation: AWS docs, Kubernetes docs, OCI/CNCF specs, RFCs, project
   docs. A blog post is acceptable only when it is the announcement of the feature.
7. Update the domain `README.md` level map if the "you leave with" sentence changed.

## Adding a runbook

Follow `docs/STYLE_GUIDE.md` §5: the title is the symptom as an operator would search for it; the
triage section is ordered commands, each with what a result means; the causes table is ordered by
frequency; "Verify the fix" is a command whose output you can paste into an incident channel. Add
the runbook to the symptom index in `playbooks/README.md` and link it from the hub document that
explains the mechanism.

## Changing the labs

- `labs/CONTRACT.md` is the interface between the applications and every deployment target. Change
  it first, then the code, then the manifests and task definitions, in one pull request.
- Images: multi-stage, pinned base tags with the digest in a comment, uid 10001, read-only root
  filesystem compatible, `linux/amd64` and `linux/arm64`. Verify with
  `docker run --rm --read-only --tmpfs /tmp --user 10001:10001 <image>`.
- Kubernetes manifests: requests and limits, `securityContext`, probes, PDB, spread constraints,
  the `app.kubernetes.io/*` labels. ECS task definitions: the field list in
  `labs/ecs/taskdefs/README.md`.
- Pin every chart, image and action version. GitHub Actions are pinned to commit SHAs with the tag
  in a trailing comment.
- Nothing may deploy without an explicit confirmation variable, and nothing may delete resources the
  templates did not create. Deploy scripts print the target account first.
- Account ids other than `123456789012` (or `000000000000` for local emulators), real ARNs, keys or
  hostnames are not accepted.

## Pull request checklist

- [ ] `make check` passes locally.
- [ ] The change is in one place and linked from the others (no duplicated explanations).
- [ ] Time-sensitive statements say "as of <month year>" and are reflected in `docs/FACTS-2026-09.md`
      (or a newer facts sheet).
- [ ] Commands were run, or the pull request says which ones were not and why.
- [ ] No emojis, no exclamation marks, no "simply / just / easily".
- [ ] Reviewed against the Well-Architected question the document claims to answer.

## Licence

Contributions are accepted under the repository's [MIT licence](LICENSE).
