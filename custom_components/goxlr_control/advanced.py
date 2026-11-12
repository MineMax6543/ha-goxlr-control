"""Advanced entity groups: hidden by default, switchable per group.

Single source of truth for which entities are "advanced". It decides
both the default enabled state of new entities and what the Configure dialog
enables/disables in the entity registry.
"""

from __future__ import annotations

import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

CONF_ADVANCED_GROUPS = "advanced_groups"

# group id -> regex matched (fullmatch) against the entity key, i.e. the
# unique_id without its "<serial>_" / "<entry_id>_" prefix.
ADVANCED_GROUPS: dict[str, re.Pattern[str]] = {
    "routing": re.compile(r"route_.+"),
    "mix_b": re.compile(r"submix_(volume|linked|output)_.+"),
    "eq": re.compile(r"eq_(gain|freq)_.+"),
    "mic_timing": re.compile(r"(gate|compressor)_(attack|release)"),
    "effects_fine": re.compile(
        r"reverb_(decay|early_level|tail_level|pre_delay|low_colour|high_colour|high_factor"
        r"|diffuse|mod_speed|mod_depth)"
        r"|echo_(feedback|tempo|delay_left|delay_right|feedback_left|feedback_right"
        r"|crossfeed_left_right|crossfeed_right_left)"
        r"|pitch_character|megaphone_post_gain|hardtune_(rate|window)"
        r"|robot_(waveform|pulse_width|threshold|dry_mix|(low|mid|high)_(gain|frequency|width))"
    ),
    "screens": re.compile(r"fader_[A-D]_screen_(number|icon|inverted)"),
    "sampler_pads": re.compile(r"sampler_[ABC]_\w+_(mode|order)|sampler_pre_record|sampler_reset_on_clear"),
    "lighting": re.compile(r"animation_(mod1|mod2|waterfall)|fader_[A-D]_display_style"),
    "other": re.compile(r"vod_mode|mic_level|effect_preset_name|log_level|open_ui_on_launch"),
}


def group_for_key(key: str) -> str | None:
    for group, pattern in ADVANCED_GROUPS.items():
        if pattern.fullmatch(key):
            return group
    return None


def enabled_groups(entry: ConfigEntry) -> set[str]:
    return set(entry.options.get(CONF_ADVANCED_GROUPS, []))


@callback
def apply_groups(hass: HomeAssistant, entry: ConfigEntry, old: set[str], new: set[str]) -> None:
    """Enable entities of newly ticked groups, disable those of unticked ones.

    Groups that didn't change are left alone, so per-entity choices made in
    the UI are kept.
    """
    turned_on, turned_off = new - old, old - new
    if not (turned_on or turned_off):
        return
    registry = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        key = (ent.unique_id or "").split("_", 1)[-1]
        group = group_for_key(key)
        if group in turned_on and ent.disabled_by is not None:
            registry.async_update_entity(ent.entity_id, disabled_by=None)
        elif group in turned_off and ent.disabled_by is None:
            registry.async_update_entity(
                ent.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
            )
