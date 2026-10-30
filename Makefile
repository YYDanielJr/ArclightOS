ARCLIGHT_WORK ?= $(if $(YYDANIEL_WORK),$(YYDANIEL_WORK),$(abspath ..))
export ARCLIGHT_WORK
.PHONY: all kernel desktop branding live source-base full-base full-iso mixed-local-base mixed-inputs mixed-iso mixed-release build-storage validation-tools nvidia iso source manifest release checkpoint release-prepare
all:
	bash scripts/build-all.sh
kernel:
	bash scripts/run-build-step.sh kernel-build.log bash scripts/build-kernel.sh
desktop:
	bash scripts/run-build-step.sh desktop-build.log bash scripts/build-desktop.sh
branding:
	bash scripts/run-build-step.sh branding-build.log bash scripts/build-branding.sh
live:
	bash scripts/run-build-step.sh live-build.log bash scripts/build-live.sh
source-base:
	bash scripts/build-source-base.sh
full-base:
	bash scripts/build-full-base.sh
full-iso:
	sudo -E bash scripts/assemble-full-iso.sh
mixed-local-base:
	bash scripts/build-mixed-local-base.sh
mixed-inputs:
	bash scripts/export-source.sh
	python3 scripts/plan-mixed-image.py "$(ARCLIGHT_WORK)" --fetch $(if $(RECOVERED_RELEASE),--from-release,)
	python3 scripts/verify-apt-snapshot.py "$(ARCLIGHT_WORK)/mixed-build/image-inputs.json" "$(ARCLIGHT_WORK)/mixed-build/apt-authentication.json"
release-prepare:
	@test -n "$(LEGACY_DIST)" || { echo 'Set LEGACY_DIST to the verified 2026-10-29 release files'; exit 2; }
	python3 scripts/prepare-release-inputs.py "$(ARCLIGHT_WORK)" --legacy-dist "$(LEGACY_DIST)" --fetch
	python3 scripts/recover-release-packages.py "$(ARCLIGHT_WORK)" --legacy-iso "$(LEGACY_DIST)/astgenne-os-trixie-amd64.iso" --receipt "$(LEGACY_DIST)/astgenne-image-inputs.json"
mixed-iso:
	sudo -E bash scripts/assemble-mixed-iso.sh
validation-tools:
	sudo -E bash scripts/prepare-system-validation.sh
build-storage:
	sudo -E bash scripts/prepare-compressed-build-storage.sh
	bash scripts/prepare-storage-metrics.sh
	sudo -E python3 scripts/measure-build-storage.py
	sudo -E bash scripts/warm-build-template.sh
nvidia:
	bash scripts/run-build-step.sh nvidia-build.log python3 scripts/build-nvidia.py
iso:
	sudo -E bash scripts/assemble-mixed-iso.sh
source:
	bash scripts/package-kernel-source.sh
manifest:
	python3 scripts/source-manifest.py --output "$(ARCLIGHT_WORK)/dist/build-host-packages.json"
release: mixed-release
mixed-release:
	@test -n "$(STAGE)" -a -n "$(TESTS)" || { echo 'Set STAGE and TESTS to the completed assembly and verified BIOS/UEFI sessions; see docs/iso-validation.md.'; exit 2; }
	python3 scripts/package-mixed-release.py "$(ARCLIGHT_WORK)" --stage "$(STAGE)" $(foreach session,$(TESTS),--test "$(session)")
checkpoint:
	bash scripts/package-checkpoint.sh
