#!/bin/sh
# Configure git to use tracked hooks from scripts/git-hooks/
git config core.hooksPath scripts/git-hooks
echo "Hooks path set to scripts/git-hooks"
