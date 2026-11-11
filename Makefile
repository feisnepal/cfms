# Makefile — Load Testing & Performance Commands (Phase 11)
# Runs from the repo root; frontend commands target frontend/.
.PHONY: ci ci-fast help dev build perf-check baseline load-test-k6 load-test-k6-local load-test-docker sentry-apply sentry-plan clean install

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

ci: ## Run the CI gates locally (8 of 10; compose-smoke and openapi-types need Docker / a live backend)
	bash scripts/ci.sh

ci-fast: ## CI gates minus the slow database and test gates
	bash scripts/ci.sh --fast

dev: ## Start the frontend dev server
	npm --prefix frontend run dev

build: ## Production build
	npm --prefix frontend run build

perf-check: build ## Bundle budget + Lighthouse perf gate against the local build
	@echo "== Bundle budgets =="
	npm --prefix frontend run bundle:budget
	@echo "== Lighthouse perf gate =="
	@npm --prefix frontend run preview -- --port 4173 & \
		PREVIEW_PID=$$!; \
		sleep 3; \
		cd frontend && npm run perf:check; \
		STATUS=$$?; \
		kill $$PREVIEW_PID 2>/dev/null; \
		exit $$STATUS

baseline: build ## Collect Lighthouse reports + save the baseline
	@npm --prefix frontend run preview -- --port 4173 & \
		PREVIEW_PID=$$!; \
		sleep 3; \
		cd frontend && npm run perf:baseline; \
		STATUS=$$?; \
		kill $$PREVIEW_PID 2>/dev/null; \
		exit $$STATUS

load-test-k6: ## Run the k6 suite (BASE_URL/API_URL/TEST_AUTH_TOKEN env)
	k6 run \
		--env BASE_URL="$(BASE_URL)" \
		--env API_URL="$(API_URL)" \
		--env TEST_AUTH_TOKEN="$(TEST_AUTH_TOKEN)" \
		--summary-export load-tests/load-test-summary.json \
		load-tests/k6-map-workspace.js

load-test-k6-local: build ## Run k6 against the local preview + backend (:8001)
	@npm --prefix frontend run preview -- --port 4173 & \
		PREVIEW_PID=$$!; \
		sleep 3; \
		k6 run \
			--env BASE_URL=http://localhost:4173 \
			--env API_URL=http://localhost:8001/api \
			load-tests/k6-map-workspace.js; \
		STATUS=$$?; \
		kill $$PREVIEW_PID 2>/dev/null; \
		exit $$STATUS

load-test-docker: ## Run k6 + InfluxDB + Grafana locally
	docker compose -f load-tests/docker-compose.k6.yml up --abort-on-container-exit

sentry-apply: ## Apply the Sentry Terraform config
	terraform -chdir=terraform apply

sentry-plan: ## Plan the Sentry Terraform changes
	terraform -chdir=terraform plan

clean: ## Clean build / test / perf artifacts
	rm -rf frontend/dist frontend/playwright-report frontend/test-results frontend/lighthouse-reports frontend/.lighthouseci

install: ## Install frontend deps + Terraform provider
	npm --prefix frontend ci --legacy-peer-deps
	terraform -chdir=terraform init
