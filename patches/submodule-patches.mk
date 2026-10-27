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
#                                     notes: behavioral deviations, apply pin
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
# - "Already applied" is detected with a dry-run reverse apply, so no stamp
#   files are needed and fresh checkouts just work.
# - Plain GNU patch(1) is used instead of `git apply` ON PURPOSE: nix
#   builds materialize submodules WITHOUT their .git directory, so the
#   sandbox has no repo to apply against. git remains optional here; it is
#   used only opportunistically for `git status` warnings.
# - All paths are resolved against this makefile's own location (REPO_DIR =
#   patches/'s parent), so the rules work from any caller CWD (top level,
#   plugins/, ...) and from /build/source in the nix sandbox.

THIS_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
# THIS_DIR ends in .../JayBird/patches/ — the repo root is one level up.
REPO_DIR := $(THIS_DIR:patches/=)
# strip the trailing slash once, for clean display and path joins
REPO_DIR := $(REPO_DIR:%/=%)
ABS_PATCHES := $(wildcard $(THIS_DIR)*/*.patch)

.PHONY: submodule-patches submodule-unpatch submodule-status

# Is the patch already applied? (dry-run reverse apply; quiet)
# $(1)=patch  $(2)=target dir
define _applied_p
if patch --dry-run --reverse --strip=1 --directory=$(2) < $(1) >/dev/null 2>&1; then true; else false; fi
endef

submodule-patches:
	@status=0; \
	for patch in $(ABS_PATCHES); do \
		subdir=$$(dirname $$patch); \
		submodule=$$(sed -n 's/^submodule:[[:space:]]*//p' $$subdir/meta.yaml); \
		if [ -z "$$submodule" ]; then \
			echo "submodule-patch: $$subdir/meta.yaml missing 'submodule:'"; \
			status=1; continue; \
		fi; \
		target="$(REPO_DIR)/$$submodule"; \
		if ! [ -d "$$target" ]; then \
			echo "submodule-patch: target missing: $$target"; \
			status=1; continue; \
		fi; \
		if patch --dry-run --strip=1 --directory=$$target < $$patch >/dev/null 2>&1; then \
			echo "submodule-patch: applying $${patch#$(REPO_DIR)/} -> $$submodule"; \
			patch --strip=1 --directory=$$target < $$patch >/dev/null || status=1; \
		elif patch --dry-run --reverse --strip=1 --directory=$$target < $$patch >/dev/null 2>&1; then \
			echo "submodule-patch: $${patch#$(REPO_DIR)/} already applied"; \
		else \
			echo "submodule-patch: $${patch#$(REPO_DIR)/} does not apply (pin moved? rebase the patch)"; \
			status=1; \
		fi; \
		if command -v git >/dev/null 2>&1; then \
			git -C $$target status --short >/dev/null 2>&1 && \
				git -C $$target status --short 2>/dev/null | head -3 | sed 's/^/submodule-patch:   /'; \
		fi; \
	done; \
	exit $$status

submodule-unpatch:
	@for patch in $(ABS_PATCHES); do \
		subdir=$$(dirname $$patch); \
		submodule=$$(sed -n 's/^submodule:[[:space:]]*//p' $$subdir/meta.yaml); \
		target="$(REPO_DIR)/$$submodule"; \
		if patch --dry-run --reverse --strip=1 --directory=$$target < $$patch >/dev/null 2>&1; then \
			echo "submodule-unpatch: reverting $${patch#$(REPO_DIR)/} in $$submodule"; \
			patch --reverse --strip=1 --directory=$$target < $$patch >/dev/null || exit 1; \
		fi; \
	done

submodule-status:
	@for patch in $(ABS_PATCHES); do \
		subdir=$$(dirname $$patch); \
		submodule=$$(sed -n 's/^submodule:[[:space:]]*//p' $$subdir/meta.yaml); \
		target="$(REPO_DIR)/$$submodule"; \
		if patch --dry-run --reverse --strip=1 --directory=$$target < $$patch >/dev/null 2>&1; then \
			echo "applied:   $${patch#$(REPO_DIR)/} ($$submodule)"; \
		elif patch --dry-run --strip=1 --directory=$$target < $$patch >/dev/null 2>&1; then \
			echo "unapplied: $${patch#$(REPO_DIR)/} ($$submodule)"; \
		else \
			echo "MISMATCH:  $${patch#$(REPO_DIR)/} ($$submodule) neither applies nor reverses — pin moved?"; \
		fi; \
	done
