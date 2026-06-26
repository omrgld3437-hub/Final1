# ayserose — Makefile

.PHONY: start stop restart deploy run dev setup meta test hooks git-log logs-clean

start:
	./ops/start.command

stop:
	./stop.command

restart:
	./ops/restart.command

deploy:
	./ops/deploy.sh

run:
	./ops/run.sh

dev: run

setup:
	./ops/Kurulum.bat

meta:
	python3 scripts/devops/generate_folder_readmes.py
	python3 scripts/devops/sync_module_meta.py
	python3 scripts/devops/sync_ana_basliklar.py

hooks:
	bash scripts/devops/install_git_hooks.sh

git-log:
	python3 scripts/devops/sync_git_log.py

test:
	PYTHONPATH=. .venv/bin/pytest tests/ -q

test-param-assistant-blackbox:
	PYTHONPATH=. python3 -m pytest tests/dynamic_param_score/test_param_assistant_blackbox.py -q

test-param-assistant-e2e:
	PYTHONPATH=. python3 -m pytest tests/e2e/test_param_assistant_user_flow.py -q

param-assistant-e2e-audit:
	PYTHONPATH=. python3 tools/param_pool/param_assistant_e2e_audit.py --symbols BTCUSDT,ETHUSDT,SOLUSDT,ADAUSDT,ASRUSDT,SFPUSDT,PROVEUSDT,TONUSDT,ENJUSDT --budgets 50,100,1000 --scenarios first_start,has_base --dry-run

logs-clean:
	.venv/bin/python scripts/maintenance/manage_logs.py --force
