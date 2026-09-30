#!/usr/bin/env bash
# Repository validation. Run from anywhere: tools/check.sh
# Uses .venv (python -m venv .venv && .venv/bin/pip install pyyaml cfn-lint) when present.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="python3"
if [[ -x .venv/bin/python ]]; then PY=".venv/bin/python"; fi

status=0

echo "== docs: headings, links, language, yaml/json"
"$PY" tools/check_docs.py || status=1

if [[ -d labs/ecs/cloudformation ]]; then
  echo "== cfn-lint"
  if [[ -x .venv/bin/cfn-lint ]]; then
    .venv/bin/cfn-lint labs/ecs/cloudformation/*.yaml labs/pipelines/codepipeline/*.yaml || status=1
  elif command -v cfn-lint >/dev/null 2>&1; then
    cfn-lint labs/ecs/cloudformation/*.yaml labs/pipelines/codepipeline/*.yaml || status=1
  else
    echo "cfn-lint not installed; skipping (pip install cfn-lint)"
  fi
fi

if [[ -d labs/eks/manifests ]]; then
  echo "== kubeconform"
  if command -v kubeconform >/dev/null 2>&1; then
    find labs/eks/manifests labs/eks/gitops labs/eks/cluster -name '*.yaml' -not -name 'kustomization.yaml' -not -name 'eksctl-*.yaml' -print0 \
      | xargs -0 kubeconform -strict -ignore-missing-schemas -summary \
        -schema-location default \
        -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
      || status=1
  else
    echo "kubeconform not installed; skipping (brew install kubeconform)"
  fi
fi

echo "== shellcheck"
if command -v shellcheck >/dev/null 2>&1; then
  find . -name '*.sh' -not -path '*/node_modules/*' -not -path './.venv/*' -not -path './.git/*' -print0 | xargs -0 shellcheck || status=1
else
  echo "shellcheck not installed; skipping"
fi

if [[ $status -eq 0 ]]; then echo "ALL CHECKS PASSED"; else echo "CHECKS FAILED"; fi
exit $status
