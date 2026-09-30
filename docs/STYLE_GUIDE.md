# Style guide and document templates

This file is the contract every document in the repository follows. It exists so that sixty
documents written by different hands read as one book. Validation scripts in `tools/` enforce the
mechanical parts (headings, links, language); the rest is judgment.

## 1. Repository shape

```text
README.md                 front door: what this is, the level ladder, how to navigate
LEARNING_PATHS.md         ordered reading + labs + checkpoints per level (100/200/300/400)
GLOSSARY.md               one-line definitions, alphabetical
hub/NN-<domain>/          knowledge hub: README + L100/L200/L300/L400 documents per domain
labs/                     one coherent runnable system (apps, local compose, ECS, EKS, Batch, pipelines)
playbooks/                operations: incident runbooks, DR plan and drills, upgrade runbooks
reference/                lookup tables: metrics catalog, ports/link-local, decisions, quotas, dates
tools/                    validation scripts used by `make check`
docs/                     this guide, the verified facts sheet, the file manifest
```

Levels are the depth axis and **live inside each domain**; domains are the topic axis.
`LEARNING_PATHS.md` stitches one level across all domains into a curriculum.

## 2. What each level means

| Level | Reader | Depth contract | Typical artifacts |
| --- | --- | --- | --- |
| 100 | Has run `docker run`, has an AWS account, new to the component | Precise concepts and vocabulary, the problem it solves, the two or three decisions a beginner faces. No internals. Short config snippets only. | Diagram, comparison table, first commands |
| 200 | Builds and ships services with the component | Configuration-level knowledge: every important field/flag, how to wire it to neighbors, sane defaults, the first ten mistakes | Real manifests / task definitions / CLI, wiring tables |
| 300 | Operates it in production, gets paged | Internals: processes, packets, API calls, state machines, timing, limits; how to prove a diagnosis with commands; tuning | Sequence diagrams, packet/process walkthroughs, `kubectl`/`aws` forensics, quantified limits |
| 400 | Designs platforms for many teams / regions | Architecture at scale, trade-offs with numbers, cost, multi-account/multi-region, failure stories, migration paths, what breaks first | Decision records, capacity math, reference architectures, anti-patterns |

Rules of thumb:

- A 100 document must be correct without being complete; a 400 document must be complete about
  trade-offs even where it is not prescriptive.
- Do not repeat a lower level. Link to it ("see L200 §3") and go deeper.
- Every level answers **why use it / why not**, **how it interacts**, **how it fails**, **what to
  measure**, **how to test**, **what DR means here**, and **which Well-Architected pillar it touches**.
  The template below makes those mandatory sections.

## 3. Leveled document template (hub/*/L*.md)

Every `L100-*.md`, `L200-*.md`, `L300-*.md`, `L400-*.md` file has **exactly these eleven H2
headings, in this order, numbered as shown**. The validator checks them.

```markdown
# <Domain> · L<NNN> — <Title>

**Level:** <100|200|300|400> · **Time:** ~<N> min · **Prerequisites:** <links or "none">

**After this document you can:**

- <capability 1>
- <capability 2>
- <capability 3>

## 1. Mental model

One diagram (Mermaid or fenced ASCII) plus the one-paragraph explanation a senior engineer would
give at a whiteboard. Name the problem the component exists to solve.

## 2. Concepts

The body. H3 subsections. Tables for comparisons, fenced code for anything a reader will type or
paste. This section carries most of the length budget.

## 3. How it interacts with the rest of AWS

A table: `Component | Talks to | Protocol/API | Prerequisite (IAM, network, DNS) | What breaks if missing`.
Then prose on the two or three interactions that surprise people.

## 4. Use it when / avoid it when

Two bullet lists, then a short "alternatives" list with the trade-off in one line each.

## 5. Well-Architected view

A table with the six pillars (Operational Excellence, Security, Reliability, Performance
Efficiency, Cost Optimization, Sustainability): what this component gives you, what it costs you,
and the concrete practice to apply. Reference the relevant lens (Container Build Lens, EKS Best
Practices Guide, ECS Best Practices Guide) where one exists.

## 6. Failure modes and troubleshooting

A table: `Symptom | Likely cause | How to confirm (command/metric) | Fix`. Link to the matching
`playbooks/incidents/*.md` when one exists.

## 7. Signals: metrics, logs, traces

Bulleted list of the metrics that matter at this level: name, source (CloudWatch namespace /
Prometheus exporter / control-plane log), what a bad value means, and a starting alarm threshold
where one is defensible. Point to `reference/metrics-catalog.md` for the full table.

## 8. Testing and DR notes

How to test this layer (unit, integration, load, chaos, game day) and what disaster recovery means
for it: what state exists, where it is backed up, how it is rebuilt, and what RTO/RPO it can support.

## 9. Hands-on

Exact commands or links into `labs/` that exercise what the document taught. State what the
reader should observe.

## 10. Check yourself

Five questions. Answers folded in `<details><summary>Answer</summary>…</details>`.

## 11. Sources

Primary documentation only (AWS docs, Kubernetes docs, OCI/CNCF specs, RFCs, project docs).
One line each: title — URL. No blogs unless they are the only primary source (announcements).
```

Length budgets (lines, including tables and code): L100 200–350 · L200 300–550 · L300 400–750 ·
L400 400–750. Longer is acceptable when the extra lines are tables or diagrams, not prose padding.

## 4. Domain README template (hub/NN-<domain>/README.md)

```markdown
# NN · <Domain name>

One paragraph: what this domain covers and why it is its own domain.

## Level map

| Level | Document | You leave with |
| --- | --- | --- |
| 100 | [L100 …](L100-….md) | … |
| 200 | … | … |
| 300 | … | … |
| 400 | … | … |

## Components covered

Bullet list of every product/component/term handled in this domain, each with the level where it
is treated in depth. This is the checklist a reader uses to find "where is X".

## Related

Links to the labs, playbooks and reference tables that belong to this domain.
```

## 5. Playbook template (playbooks/**/*.md)

```markdown
# <Symptom or procedure as the operator would type it into a search box>

**Applies to:** ECS | EKS | both · **Severity guide:** … · **Time to first fix:** …

## Symptoms
## Triage in five minutes   (ordered commands; each line says what a result means)
## Causes and fixes         (table or subsections, most common first)
## Verify the fix
## Prevent it               (link to the hub document and Well-Architected practice)
## Related
```

DR and upgrade runbooks may replace "Symptoms/Triage" with "Preconditions/Steps/Rollback" but keep
"Verify" and "Related".

## 6. Writing rules

- **Voice:** direct, technical, second person ("you"). Explain like a senior engineer to a peer;
  never condescending, never marketing. Prefer "X does Y because Z" over adjectives.
- **Precision beats breadth:** a wrong detail costs more than a missing one. When a number or
  behavior might have changed, say "as of September 2026" and link the primary doc; when you are
  not sure, write "verify in the current documentation" instead of guessing.
- **Use `docs/FACTS-2026-09.md`** for anything time-sensitive (versions, end-of-support dates,
  feature availability). Do not contradict it.
- **Always answer the why:** why the component exists, why a default is what it is, why the
  failure happens. Mechanism, then rule.
- **Show the failure, not only the happy path.** Every level has a troubleshooting table.
- **Commands are real.** `aws`, `kubectl`, `docker`, `ctr`, `crictl` invocations must be valid
  syntax with realistic flags. Use region `us-east-1`, account `123456789012`, cluster names
  `shopfront-dev`, VPC CIDR `10.42.0.0/16`, domain `shopfront.example.com`.
- **Diagrams:** Mermaid (`flowchart`, `sequenceDiagram`) or fenced ASCII. Keep them small enough
  to read on a phone.
- **Tables** for comparisons and matrices; **prose** for reasoning; **bullets** for enumerations.
- **Line length:** soft wrap at 100 characters in prose. Tables and URLs may exceed it.
- **Inclusive language:** never `master`, `slave`, `whitelist`, `blacklist` — use primary/replica, <!-- term-ok -->
  allowlist/denylist. When a third-party API forces the term (for example a Kafka or Jenkins
  configuration key), quote it as code and append the HTML comment `<!-- term-ok -->` to that line
  (or `# term-ok` in code). The validator greps for these terms and skips marked lines.
- **No secrets, no real identifiers:** the only account ID is `123456789012`; no ARNs of real
  accounts, no keys, no employee names.
- **Dates and versions:** Kubernetes versions as `1.36`; EKS platform versions as `eks.N`; pin
  Helm chart and container image versions in labs.
- **Links:** relative links inside the repo (validated); absolute links only to external sources.
  Link the glossary the first time a term appears in a domain, not every time.
- **No emojis, no exclamation marks, no "simply/just/easily".**
- **Markdown:** ATX headings, one H1 per file, fenced code with a language tag, no HTML except
  `<details>` for folded answers.

## 7. Code and IaC rules (labs/)

- Multi-stage Dockerfiles, pinned base images by tag **and** digest comment, non-root user
  (uid 10001), read-only root filesystem compatible, `linux/amd64` and `linux/arm64`.
- Twelve-factor configuration through environment variables listed in `labs/CONTRACT.md`.
- Health endpoints `/healthz` (liveness), `/readyz` (readiness), `/metrics` (Prometheus text).
- Structured JSON logs to stdout with `trace_id` when a trace is active.
- Graceful shutdown on SIGTERM within 20 seconds.
- Kubernetes manifests: `resources` requests and limits on every container, `securityContext`
  (runAsNonRoot, drop ALL capabilities, seccomp RuntimeDefault, readOnlyRootFilesystem where the
  app allows), probes, PodDisruptionBudget, topology spread, labels
  `app.kubernetes.io/name|part-of|version`.
- ECS task definitions: `awsvpc`, explicit `cpu`/`memory`, `healthCheck`, `stopTimeout`,
  `readonlyRootFilesystem: true`, `user: "10001"`, secrets via `secrets[]` (never plain env),
  `awslogs` or FireLens logging, `linuxParameters.initProcessEnabled: true`.
- CloudFormation must pass `cfn-lint`; Kubernetes manifests must pass `kubeconform`
  (`-ignore-missing-schemas` for CRDs); shell must pass `shellcheck`.
- Nothing deploys automatically. Deploy scripts print the account they target and require an
  explicit confirmation variable. Never include deletion of resources that a reader did not create
  with these templates.

## 8. Validation (`make check`)

`tools/check.sh` runs: heading structure of every leveled doc, relative link resolution, inclusive
language and account-ID grep, YAML/JSON parse, `cfn-lint` on `labs/ecs/cloudformation`, `kubeconform`
on `labs/eks`, `shellcheck` on scripts. Keep it green.
