.PHONY: help venv install run stop restart clean deactivate debug

VENV_DIR = venv
PID_FILE = app.pid
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip

help:
	@echo "可用命令:"
	@echo "  make install    - 创建虚拟环境并安装依赖"
	@echo "  make run        - 启动应用"
	@echo "  make debug      - 以调试模式启动应用"
	@echo "  make stop       - 停止应用"
	@echo "  make restart    - 重启应用"
	@echo "  make clean      - 清理生成的文件和虚拟环境"
	@echo "  make deactivate - 退出虚拟环境"

venv:
	@echo "创建Python虚拟环境..."
	@python3 -m venv $(VENV_DIR)
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.txt
	@echo "虚拟环境创建完成"

install: venv
	@echo "安装依赖..."
	@$(PIP) install -r requirements.txt
	@echo "依赖安装完成"

run: venv
	@echo "启动应用..."
	@if [ -f $(PID_FILE) ]; then \
		echo "应用已在运行中，请先使用 make stop 停止"; \
		exit 1; \
	fi
	@$(PYTHON) -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload & echo $$! > $(PID_FILE)
	@echo "应用已启动，访问 http://localhost:8000"
	@echo "PID: $$(cat $(PID_FILE))"

debug: venv
	@echo "以调试模式启动应用..."
	@if [ -f $(PID_FILE) ]; then \
		echo "应用已在运行中，请先使用 make stop 停止"; \
		exit 1; \
	fi
	@$(PYTHON) -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload --reload & echo $$! > $(PID_FILE)
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

deactivate:
	@echo "退出虚拟环境..."
	@deactivate || echo "虚拟环境未激活"
	@echo "虚拟环境已退出" 