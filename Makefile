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

logs-clean:
	.venv/bin/python scripts/maintenance/manage_logs.py
