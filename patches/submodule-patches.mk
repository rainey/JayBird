# Build-time submodule patches
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Submodule sources stay pristine in git; fixes JayBird needs are tracked
# here as git-format patches and applied into the submodule working tree
# at build time. Nothing patched is ever committed inside a submodule.
#
# Layout:
#   patches/<Subdir>/<name>.patch   git-format diff whose paths are relative
#                                   to the submodule root, generated with:
#                                     git -C plugins/<Subdir> diff
#   patches/<Subdir>/meta.yaml      metadata, at minimum:
#                                     submodule: plugins/<Subdir>
#                                   optional keys (informational):
#                                     reason: why the patch exists
#                                     notes: behavioral deviations, etc.
#
# Targets (from any directory):
#   make -f patches/submodule-patches.mk submodule-patches   apply
#   make -f patches/submodule-patches.mk submodule-unpatch   revert
#   make -f patches/submodule-patches.mk submodule-status    show state
# plugins/Makefile runs `submodule-patches` automatically before compiling,
# so a plain build patches on demand.
#
# Rules:
# - A patch must apply cleanly to the pinned submodule commit; if a pin is
#   ever moved, rebase and regenerate with:
#       git -C plugins/<Subdir> diff > patches/<Subdir>/<name>.patch
# - "Already applied" is detected with `git apply --reverse --check`, so no
#   stamp files are needed and fresh checkouts just work.
# - All paths are resolved against this makefile's own location (REPO_DIR =
#   patches/'s parent), so the rules work from any caller CWD (top level,
#   plugins/, ...).

THIS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
# THIS_DIR ends in .../JayBird/patches/ — the repo root is one level up.
# ($(dir ...) keeps the last component when the path already ends in /, so
# strip the trailing "patches/" explicitly.)
REPO_DIR := $(THIS_DIR:patches/=)
ABS_PATCHES := $(wildcard $(THIS_DIR)*/*.patch)

.PHONY: submodule-patches submodule-unpatch submodule-status

submodule-patches:
	@status=0; \
	for patch in $(ABS_PATCHES); do \
		subdir=$$(dirname $$patch); \
		submodule=$$(sed -n 's/^submodule:[[:space:]]*//p' $$subdir/meta.yaml); \
		if [ -z "$$submodule" ]; then \
			echo "submodule-patch: $$subdir/meta.yaml missing 'submodule:'"; \
			status=1; continue; \
		fi; \
		submodule="$(REPO_DIR:%/=%)/$$submodule"; \
		if git -C $$submodule apply --check $$patch 2>/dev/null; then \
			echo "submodule-patch: applying $${patch#$(REPO_DIR)/} -> $$submodule"; \
			git -C $$submodule apply $$patch || status=1; \
		elif git -C $$submodule apply --reverse --check $$patch 2>/dev/null; then \
			echo "submodule-patch: $${patch#$(REPO_DIR)/} already applied"; \
		else \
			echo "submodule-patch: $${patch#$(REPO_DIR)/} does not apply (pin moved? rebase the patch)"; \
			status=1; \
		fi; \
	done; \
	exit $$status

submodule-unpatch:
	@for patch in $(ABS_PATCHES); do \
		subdir=$$(dirname $$patch); \
		submodule=$$(sed -n 's/^submodule:[[:space:]]*//p' $$subdir/meta.yaml); \
		submodule="$(REPO_DIR:%/=%)/$$submodule"; \
		if git -C $$submodule apply --reverse --check $$patch 2>/dev/null; then \
			echo "submodule-unpatch: reverting $${patch#$(REPO_DIR)/} in $$submodule"; \
			git -C $$submodule apply --reverse $$patch || exit 1; \
		fi; \
	done

submodule-status:
	@for patch in $(ABS_PATCHES); do \
		subdir=$$(dirname $$patch); \
		submodule=$$(sed -n 's/^submodule:[[:space:]]*//p' $$subdir/meta.yaml); \
		submodule="$(REPO_DIR:%/=%)/$$submodule"; \
		if git -C $$submodule apply --reverse --check $$patch 2>/dev/null; then \
			echo "applied:   $${patch#$(REPO_DIR)/} ($$submodule)"; \
		elif git -C $$submodule apply --check $$patch 2>/dev/null; then \
			echo "unapplied: $${patch#$(REPO_DIR)/} ($$submodule)"; \
		else \
			echo "MISMATCH:  $${patch#$(REPO_DIR)/} ($$submodule) neither applies nor reverses — pin moved?"; \
		fi; \
	done
