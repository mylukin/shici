.PHONY: help run stop restart venv

VENV_DIR = venv
PID_FILE = app.pid
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip

help:
	@echo "可用命令:"
	@echo "  make help     - 显示帮助信息"
	@echo "  make run      - 创建虚拟环境并启动应用"
	@echo "  make stop     - 停止运行中的应用"
	@echo "  make restart  - 重启应用"

venv:
	@echo "创建Python虚拟环境..."
	@python3 -m venv $(VENV_DIR)
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.txt
	@echo "虚拟环境创建完成"

run: venv
	@echo "启动应用..."
	@if [ -f $(PID_FILE) ]; then \
		echo "应用已在运行中，请先使用 make stop 停止"; \
		exit 1; \
	fi
	@$(PYTHON) -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload & echo $$! > $(PID_FILE)
	@echo "应用已启动，访问 http://localhost:8000"
	@echo "PID: $$(cat $(PID_FILE))"

stop:
	@if [ -f $(PID_FILE) ]; then \
		echo "停止应用 (PID: $$(cat $(PID_FILE)))..."; \
		kill $$(cat $(PID_FILE)) 2>/dev/null || true; \
		rm $(PID_FILE); \
		echo "应用已停止"; \
	else \
		echo "应用未运行"; \
	fi

restart: stop run

clean:
	@echo "清理项目..."
	@rm -rf $(VENV_DIR) __pycache__ static/audio/* $(PID_FILE)
	@find . -type d -name __pycache__ -exec rm -rf {} +
	@echo "清理完成" 