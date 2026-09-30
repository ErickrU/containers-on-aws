.PHONY: check build-images up down smoke logs clean

COMPOSE := docker compose -f labs/local/compose.yaml

check:            ## structure, links, language, YAML/JSON, cfn-lint, kubeconform, shellcheck
	tools/check.sh

build-images:     ## build the five shopfront images locally
	$(COMPOSE) build

up:               ## start the whole shopfront system locally
	$(COMPOSE) up -d --build
	@echo "orders   http://localhost:8080  | catalog http://localhost:8081"
	@echo "jaeger   http://localhost:16686 | elasticmq http://localhost:9325"

smoke:            ## end-to-end check: cache, order, fulfillment, metrics, analytics
	labs/local/smoke.sh

report:           ## run the batch report job once against the local stack
	$(COMPOSE) --profile jobs run --rm report-job

logs:
	$(COMPOSE) logs -f --tail=100

down:
	$(COMPOSE) --profile jobs down -v --remove-orphans

clean: down
	rm -rf labs/local/out
