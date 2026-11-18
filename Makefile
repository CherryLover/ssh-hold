SHELL := /bin/bash

VERSION ?= $(shell sed -n 's/^VERSION="\(.*\)"$$/\1/p' bin/ssh-hold | head -1)
PREFIX ?= $(HOME)/.local
DIST := dist
PKG := $(DIST)/ssh-hold-$(VERSION)

.PHONY: help test test-wire lint dist standalone clean install uninstall version

help:
	@echo "make test        跑单元测试（不联网，不碰真实服务器）"
	@echo "make test-wire   跑本地回环的真实 SSH 密码握手测试（需要 uv）"
	@echo "make lint        shellcheck + python 语法检查（装了才跑）"
	@echo "make dist        打出发布包 tar.gz、单文件版和校验和"
	@echo "make install     装到 PREFIX（默认 ~/.local）"
	@echo "make uninstall   卸载"
	@echo "make clean       删掉 dist/"

version:
	@echo $(VERSION)

test:
	cd tests && python3 -m unittest -v test_paste test_skill test_cli test_myshell

test-wire:
	cd tests && uv run --with paramiko python -m unittest -v test_wire

lint:
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck -S warning bin/ssh-hold install.sh lib/askpass; \
	else \
		echo "没装 shellcheck，跳过 shell 检查"; \
	fi
	@bash -n bin/ssh-hold install.sh
	@python3 -m py_compile lib/paste.py lib/myshell.py scripts/build-standalone.py
	@echo "检查通过"

standalone:
	@mkdir -p $(DIST)
	python3 scripts/build-standalone.py "$(VERSION)" "$(DIST)/ssh-hold"

dist: clean standalone
	@mkdir -p $(PKG)/bin $(PKG)/lib $(PKG)/man $(PKG)/completions $(PKG)/skill
	sed 's/^VERSION="[^"]*"$$/VERSION="$(VERSION)"/' bin/ssh-hold > $(PKG)/bin/ssh-hold
	chmod 755 $(PKG)/bin/ssh-hold
	cp lib/askpass $(PKG)/lib/askpass && chmod 755 $(PKG)/lib/askpass
	cp lib/paste.py lib/myshell.py $(PKG)/lib/
	cp skill/SKILL.md $(PKG)/skill/
	cp man/ssh-hold.1 $(PKG)/man/
	cp completions/ssh-hold.bash completions/_ssh-hold $(PKG)/completions/
	cp install.sh $(PKG)/install.sh && chmod 755 $(PKG)/install.sh
	cp README.md LICENSE CHANGELOG.md $(PKG)/
	cd $(DIST) && tar -czf ssh-hold-$(VERSION).tar.gz ssh-hold-$(VERSION)
	rm -rf $(PKG)
	cd $(DIST) && { command -v sha256sum >/dev/null 2>&1 && sha256sum ssh-hold-$(VERSION).tar.gz ssh-hold \
		|| shasum -a 256 ssh-hold-$(VERSION).tar.gz ssh-hold; } > SHA256SUMS
	@echo
	@ls -l $(DIST)
	@cat $(DIST)/SHA256SUMS

install:
	./install.sh --prefix "$(PREFIX)"

uninstall:
	./install.sh --prefix "$(PREFIX)" --uninstall

clean:
	rm -rf $(DIST)
