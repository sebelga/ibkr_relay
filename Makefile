.PHONY: deploy destroy pause resume sync order poll logs stats ssh help

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-12s %s\n", $$1, $$2}'

deploy: ## Deploy infrastructure (Terraform + Docker)
	./deploy.sh

destroy: ## Permanently destroy all infrastructure
	./destroy.sh

pause: ## Snapshot droplet + delete (save costs)
	./pause.sh

resume: ## Restore droplet from snapshot
	./resume.sh

sync: ## Push .env + restart all services (or: make sync S=gateway)
	./sync-env.sh $(S)

order: ## Place an order (e.g. make order Q=2 SYM=TSLA T=MKT)
	./order.sh $(Q) $(SYM) $(T) $(P)

poll: ## Trigger an immediate Flex poll
	./poll-now.sh

logs: ## Stream poller logs (Ctrl+C to stop)
	@. ./.env && ssh -i $${SSH_KEY:-$$HOME/.ssh/ibkr-relay} root@$$DROPLET_IP \
		'cd /opt/ibkr-relay && docker compose logs -f $(or $(S),poller)'

stats: ## Show container resource usage
	@. ./.env && ssh -i $${SSH_KEY:-$$HOME/.ssh/ibkr-relay} root@$$DROPLET_IP \
		'docker stats --no-stream'

ssh: ## SSH into the droplet
	@. ./.env && ssh -i $${SSH_KEY:-$$HOME/.ssh/ibkr-relay} root@$$DROPLET_IP
