/*
 * InfNoise (InfiniteNoise) shim — provides the non-registration parts of
 * InfNoise/src/plugin.cpp that other translation units reference.
 *
 * InfNoise/src/plugin.cpp itself is excluded from the build (see
 * plugins/Makefile): its init() and pluginInstance definitions belong to
 * Cardinal's static plugin loader (plugins.cpp/plugins-jaybird.cpp define
 * pluginInstance__InfNoise and register the 85 models), and compiling it
 * would duplicate those symbols at the final link. Everything else in
 * plugin.cpp is live code — settings helpers (panel theme, port prefix,
 * logo status lights, panel mount), the port-prefix constants and the
 * InfNoiseModuleWidget overlay methods declared in plugin.hpp — so it is
 * replicated here verbatim (minus init/pluginInstance/addModels), with
 * the same -D model renames as the rest of the plugin.
 *
 * Derived from InfNoise/src/plugin.cpp (GPL-3.0-or-later,
 * (c) 2024-2026 Pelle Liljendal). If the submodule pin is moved and these
 * helpers change upstream, update this file to match.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include <rack.hpp>
#include "InfNoise/src/plugin.hpp"
#include "InfNoise/src/inComponents.hpp"

// getJsonInt/getJsonBool live in the plugin's src/ (inUtil.hpp); the
// Makefile rule adds -IInfNoise/src via $(INFNOISE_FLAGS).

// NOTE: pluginInstance is NOT defined here — Cardinal's generated
// plugins-jaybird.cpp defines pluginInstance__InfNoise; the plain
// 'pluginInstance' extern declaration in plugin.hpp is satisfied by the
// -DpluginInstance rename in the TUs that need it.

const char kInfNoiseMonoPortPrefix[] = "(m) ";
const char kInfNoisePolyPortPrefix[] = "(p) ";

InfNoiseModuleWidget::~InfNoiseModuleWidget() {
	delete disableOverlayManager;
	disableOverlayManager = nullptr;
}

InfNoiseDisableOverlayManager& InfNoiseModuleWidget::getDisableOverlayManager() {
	if (!disableOverlayManager) {
		disableOverlayManager = new InfNoiseDisableOverlayManager(this);
	}
	else {
		disableOverlayManager->setOwner(this);
	}

	return *disableOverlayManager;
}

void InfNoiseModuleWidget::refreshDisableOverlayThemeColors() {
	const bool d = effectivePanelIsDark();
	lastOverlayPanelIsDarkCache = d;
	if (!disableOverlayManager) {
		return;
	}
	disableOverlayManager->refreshOverlayThemeColors(d);
}

void InfNoiseModuleWidget::tickDisableOverlayThemeFromRack() {
	if (!disableOverlayManager) {
		return;
	}
}

void InfNoiseModuleWidget::syncInfNoiseGlobalSettings() {
	if (getPanelTheme() != appliedPanelTheme) {
		applyPanelTheme();
		appliedPanelTheme = getPanelTheme();
	}
	if (getShowPortPrefix() != appliedPortPrefix) {
		applyPortPrefixes();
		appliedPortPrefix = getShowPortPrefix();
	}
	if (getShowLogoStatusLights() != appliedLogoStatusLights) {
		if (auto* infMod = dynamic_cast<InfNoiseModule*>(module)) {
			infMod->refreshProcessQualityLights(true);
			infMod->refreshClipRangeLights(true);
		}
		appliedLogoStatusLights = getShowLogoStatusLights();
	}
}

void InfNoiseModuleWidget::step() {
	syncInfNoiseGlobalSettings();
	tickDisableOverlayThemeFromRack();
	ModuleWidget::step();
}

void InfNoiseModuleWidget::applyPortPrefixes() {
	engine::Module* mod = getModule();
	if (!mod) return;
	bool show = getShowPortPrefix();
	const std::string prefixM = kInfNoiseMonoPortPrefix;
	const std::string prefixP = kInfNoisePolyPortPrefix;
	for (widget::Widget* w : getInputs()) {
		app::PortWidget* pw = dynamic_cast<app::PortWidget*>(w);
		if (!pw) continue;
		int id = pw->portId;
		engine::PortInfo* info = mod->getInputInfo(id);
		if (!info) continue;
		std::string& name = info->name;
		if (show) {
			if (name.size() < 4 || (name.substr(0, 4) != prefixM && name.substr(0, 4) != prefixP)) {
				bool isPoly = (dynamic_cast<infNoiseThemedPolyPort*>(pw) != nullptr);
				name = (isPoly ? prefixP : prefixM) + name;
			}
		} else {
			if (name.size() >= 4 && (name.substr(0, 4) == prefixM || name.substr(0, 4) == prefixP))
				name = name.substr(4);
		}
	}
	for (widget::Widget* w : getOutputs()) {
		app::PortWidget* pw = dynamic_cast<app::PortWidget*>(w);
		if (!pw) continue;
		int id = pw->portId;
		engine::PortInfo* info = mod->getOutputInfo(id);
		if (!info) continue;
		std::string& name = info->name;
		if (show) {
			if (name.size() < 4 || (name.substr(0, 4) != prefixM && name.substr(0, 4) != prefixP)) {
				bool isPoly = (dynamic_cast<infNoiseThemedPolyPort*>(pw) != nullptr);
				name = (isPoly ? prefixP : prefixM) + name;
			}
		} else {
			if (name.size() >= 4 && (name.substr(0, 4) == prefixM || name.substr(0, 4) == prefixP))
				name = name.substr(4);
		}
	}
}

static std::string inSettingsFileName = asset::user("InfiniteNoise.json");
static const int gSettingsCurrentJson = 1; // Manually incremented for breaking changes to InfiniteNoise.json
static int gSettingsJsonVersion = gSettingsCurrentJson; // Loaded from file; defaults to 1 if missing
static panelThemeType gPanelTheme = theme_Auto;
static bool gShowPortPrefix = true;
static bool gShowLogoStatusLights = true;
static panelMountMode gPanelMountMode = mount_Random;

static const std::vector<std::string> gMountStyleNames = {
	"None",
	"Mounting points only",
	"Two screws",
	"Four screws",
	"Random"
};

const std::vector<std::string>& getMountStyleNames() {
	return gMountStyleNames;
}

panelThemeType getPanelTheme() {
	return gPanelTheme;
}

panelMountMode getPanelMountMode() {
	return gPanelMountMode;
}

void inLoadSettings() { // Load Infinite-Noise settings (panel theme, port prefix, etc.)
	FILE* file = fopen(inSettingsFileName.c_str(), "r");
	if (file) {
		json_error_t error;
		json_t* rootJ = json_loadf(file, 0, &error);

		gSettingsJsonVersion = getJsonInt(rootJ, "jsonVersion", 1);

		int val = getJsonInt(rootJ, "panelTheme", (int)gPanelTheme);
		if (val >= theme_Auto && val <= theme_Black) {
			gPanelTheme = (panelThemeType)val;
		}

		gShowPortPrefix = getJsonBool(rootJ, "showPortPrefix", gShowPortPrefix);
		gShowLogoStatusLights = getJsonBool(rootJ, "showLogoStatusLights", gShowLogoStatusLights);

		val = getJsonInt(rootJ, "panelMountMode", (int)gPanelMountMode);
		if (val >= mount_None && val <= mount_Random) {
			gPanelMountMode = (panelMountMode)val;
		}

		fclose(file);
		json_decref(rootJ);
	}
}

void inSaveSettings() { // Save Infinite-Noise settings (panel theme, port prefix, etc.)
	FILE* file = fopen(inSettingsFileName.c_str(), "w");
	if (file) {
		json_t* rootJ = json_object();

		gSettingsJsonVersion = gSettingsCurrentJson; // Always saved as current version
		json_object_set_new(rootJ, "jsonVersion", json_integer(gSettingsJsonVersion));

		json_object_set_new(rootJ, "panelTheme", json_integer((int)gPanelTheme));
		json_object_set_new(rootJ, "showPortPrefix", json_boolean(gShowPortPrefix));
		json_object_set_new(rootJ, "showLogoStatusLights", json_boolean(gShowLogoStatusLights));
		json_object_set_new(rootJ, "panelMountMode", json_integer((int)gPanelMountMode));
		json_dumpf(rootJ, file, JSON_INDENT(2) | JSON_REAL_PRECISION(9));
		fclose(file);
		json_decref(rootJ);
	}
}

bool getShowPortPrefix() {
	return gShowPortPrefix;
}

bool getShowLogoStatusLights() {
	return gShowLogoStatusLights;
}

void setShowPortPrefix(bool show) {
	if (gShowPortPrefix == show) {
		return;
	}
	gShowPortPrefix = show;
	inSaveSettings();
}

void setShowLogoStatusLights(bool show) {
	if (gShowLogoStatusLights == show) {
		return;
	}
	gShowLogoStatusLights = show;
	inSaveSettings();
}

void setPanelTheme(panelThemeType theme) {
	if (gPanelTheme == theme) {
		return;
	}

	gPanelTheme = theme;
	inSaveSettings();
}

void setPanelMountMode(panelMountMode mode) {
	if (gPanelMountMode == mode) {
		return;
	}
	if (mode < mount_None || mode > mount_Random) {
		return;
	}
	gPanelMountMode = mode;
	inSaveSettings();
}
