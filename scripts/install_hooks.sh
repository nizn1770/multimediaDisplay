#!/usr/bin/env bash
# Install the secret-scanning pre-commit hook.
cd "$(git rev-parse --show-toplevel)" && git config core.hooksPath scripts/hooks && echo "pre-commit hook installed (core.hooksPath=scripts/hooks)"
