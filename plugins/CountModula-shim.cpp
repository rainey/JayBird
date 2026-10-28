/*
 * CountModula shim — provides the non-registration parts of
 * CountModula/src/CountModula.cpp that module translation units reference.
 *
 * CountModula.cpp itself is excluded from the build (see plugins/Makefile):
 * its init() and pluginInstance definitions belong to Cardinal's static
 * plugin loader (plugins.cpp/plugins-jaybird.cpp define
 * pluginInstance__CountModula and register the models), and compiling it
 * would duplicate those symbols at the final link. Everything else in
 * CountModula.cpp is live code used by the modules, so it is replicated
 * here verbatim (minus init/pluginInstance/InitialiseModels), compiled
 * with the same -D renames as the rest of the plugin so the theme globals
 * keep their CountModula-prefixed names.
 *
 * Derived from CountModula/src/CountModula.cpp (GPL-3.0-or-later,
 * Copyright (C) 2019 Adam Verspaget). If the submodule pin is moved and
 * these helpers change upstream, update this file to match.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "CountModula.hpp"

int defaultTheme = 0;
int prevDefaultTheme = -1;

void setDefaultTheme(int themeToUse, bool previous) {
	if (previous)
		prevDefaultTheme = themeToUse;
	else
		defaultTheme = themeToUse;
}

int getDefaultTheme(bool previous) {
	return previous ? prevDefaultTheme : defaultTheme;
}

// save the given global count modula settings`
void saveSettings(json_t *rootJ) {
	std::string settingsFilename = asset::user("CountModula.json");
	
	FILE *file = fopen(settingsFilename.c_str(), "w");
	
	if (file) {
		json_dumpf(rootJ, file, JSON_INDENT(2) | JSON_REAL_PRECISION(9));
		fclose(file);
	}
}

// read the global count modula settings
json_t * readSettings() {
	std::string settingsFilename = asset::user("CountModula.json");
	FILE *file = fopen(settingsFilename.c_str(), "r");
	
	if (!file) {
		return json_object();
	}
	
	json_error_t error;
	json_t *rootJ = json_loadf(file, 0, &error);
	
	fclose(file);
	return rootJ;
}

// read the given default integer value from the global count modula settings file
int readDefaultIntegerValue(std::string setting) {
	int value = 0; // default to the standard value
	
	// read the settings file
	json_t *rootJ = readSettings();
	
	// get the default value
	json_t* jsonValue = json_object_get(rootJ, setting.c_str());
	if (jsonValue)
		value = json_integer_value(jsonValue);

	// houskeeping
	json_decref(rootJ);
	
	return value;
}

// save the given integer value in the global count modula settings file
void saveDefaultIntegerValue(std::string setting, int value) {
	// read the settings file
	json_t *rootJ = readSettings();
	
	// set the default theme value
	json_object_set_new(rootJ, setting.c_str(), json_integer(value));

	// save the updated data
	saveSettings(rootJ);
	
	// houskeeping
	json_decref(rootJ);
}

// hack for module expanders always to the right
static math::Vec eachNearestGridPosRight(math::Vec pos, std::function<bool(math::Vec pos)> f) {
	math::Vec leftPos = (pos / RACK_GRID_SIZE).round();
	math::Vec rightPos = leftPos + math::Vec(1, 0);

	while (true) {
		if (f(rightPos * RACK_GRID_SIZE))
			return rightPos * RACK_GRID_SIZE;
		rightPos.x += 1;
	}

	assert(false);
	return math::Vec();
}

// hack for module expanders always to the right
void setModulePosNearestRight(ModuleWidget* mw, math::Vec pos) {
	eachNearestGridPosRight(pos, [&](math::Vec pos) -> bool {
		return APP->scene->rack->requestModulePos(mw, pos);
	});
}

static math::Vec eachNearestGridPosLeft(math::Vec pos, std::function<bool(math::Vec pos)> f) {
	math::Vec leftPos = (pos / RACK_GRID_SIZE).round();

	while (true) {
		if (f(leftPos * RACK_GRID_SIZE))
			return leftPos * RACK_GRID_SIZE;
		leftPos.x -= 1;
	}

	assert(false);
	return math::Vec();
}

// hack for module expanders always to the left
void setModulePosNearestLeft(ModuleWidget* mw, math::Vec pos) {
	eachNearestGridPosLeft(pos, [&](math::Vec pos) -> bool {
		return APP->scene->rack->requestModulePos(mw, pos);
	});
}
