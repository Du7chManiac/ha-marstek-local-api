"""Compatibility matrix for Marstek devices across firmware and hardware versions.

DESIGN PHILOSOPHY:
------------------
This matrix exists to support the LATEST firmware versions. As older firmware versions
become obsolete, their entries can be removed from this matrix. The goal is NOT to
maintain backward compatibility indefinitely, but to handle the current generation
of devices.

MISSING FIELDS:
---------------
If a field is not present in the API response payload, that's acceptable. The sensor
layer will handle missing values and display "unknown" to the user. No special handling
is needed in this compatibility layer.

SCALING LOOKUP LOGIC:
---------------------
Matrix keys are (hardware_version, firmware_version) tuples.
Firmware version means "from this version onwards".

Example: Device with HW 2.0, FW 200
- Matrix has entries: (HW_VERSION_2, 0) and (HW_VERSION_2, 154)
- Lookup finds highest FW <= 200, which is 154
- Uses the scaling factor for (HW_VERSION_2, 154)

HARDWARE VERSIONS:
------------------
- HW 2.0: Original hardware (e.g., "VenusE")
- HW 3.0: Newer hardware (e.g., "VenusE 3.0")

All defaults are explicit in the matrix for maintainability.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Final

_LOGGER = logging.getLogger(__name__)

# Hardware version detection
HW_VERSION_2: Final = "2.0"
HW_VERSION_3: Final = "3.0"


def parse_hardware_version(device_model: str) -> str:
    """Extract hardware version from device model string.

    Examples:
        "VenusE" -> "2.0"
        "VenusE 3.0" -> "3.0"
        "VenusD" -> "2.0"
    """
    if not device_model:
        return HW_VERSION_2

    # Check for explicit version in model name
    match = re.search(r'(\d+\.\d+)', device_model)
    if match:
        return match.group(1)

    # Default to hardware version 2.0
    return HW_VERSION_2


def get_base_model(device_model: str) -> str:
    """Get base model name without hardware version suffix or whitespace.

    Examples:
        "VenusE 3.0" -> "VenusE"
        "VenusE" -> "VenusE"
        "VenusD" -> "VenusD"
        "Venus D" -> "VenusD"   (firmware reports the model with a space)
    """
    if not device_model:
        return ""

    # Drop a "<base> <ver>" suffix like "VenusE 3.0" first.
    stripped = re.sub(r'\s+\d+\.\d+.*$', '', device_model)
    # Then collapse intra-name whitespace ("Venus D" -> "VenusD") so all
    # downstream lookups can use a single canonical spelling.
    return re.sub(r'\s+', '', stripped)


class CompatibilityMatrix:
    """Centralized compatibility matrix for version-dependent value scaling.

    This class handles all firmware and hardware version-specific scaling logic
    in one location. All defaults are explicit for maintainability.
    """

    # ============================================================================
    # SCALING MATRIX
    # ============================================================================
    # Format: {field_name: {(base_model, hw_version, fw_version): divisor}}
    #
    # base_model is None for entries that apply to every model on the given
    # hardware version. A model-specific entry (e.g. "VenusD") wins over the
    # wildcard when both are applicable.
    #
    # The raw API value is DIVIDED by the divisor to get the final value.
    # Firmware version means "from this version onwards".
    # Lookup finds the highest firmware version <= actual device firmware.
    # ============================================================================

    SCALING_MATRIX: dict[str, dict[tuple[str | None, str, int], float]] = {
        # Battery temperature (°C)
        "bat_temp": {
            (None, HW_VERSION_2, 0): 1.0,      # FW 0-153: raw value in °C
            (None, HW_VERSION_2, 154): 0.1,    # FW 154+: raw value in deci-°C (÷0.1 = ×10)
            (None, HW_VERSION_3, 0): 1.0,      # FW 0+: raw value in °C
            (None, HW_VERSION_3, 139): 10.0,   # FW 0+: raw value in deca-°C (÷10)
        },

        # Battery remaining capacity from Bat.GetStatus, [Wh] per spec.
        "bat_capacity": {
            (None, HW_VERSION_2, 0): 100.0,    # FW 0-153: raw value in centi-Wh (÷100)
            (None, HW_VERSION_2, 154): 1.0,    # FW 154+: raw value in Wh
            (None, HW_VERSION_3, 0): 1.0,      # FW 0+: raw value in Wh
            (None, HW_VERSION_3, 139): 0.1,    # FW 0+: raw value in deci-Wh (÷0.1)
            # Venus D reports Wh directly (verified on FW 147; matches the
            # published API spec, which says the field is already in Wh).
            ("VenusD", HW_VERSION_2, 0): 1.0,
        },

        # Battery power (W)
        "bat_power": {
            (None, HW_VERSION_2, 0): 10.0,     # FW 0-153: raw value in deca-W (÷10)
            (None, HW_VERSION_2, 154): 1.0,    # FW 154+: raw value in W
            (None, HW_VERSION_3, 0): 1.0,      # FW 0+: raw value in W
            # Venus D reports W directly (matches spec).
            ("VenusD", HW_VERSION_2, 0): 1.0,
        },

        # Grid import energy from ES.GetStatus, [Wh] per spec.
        "total_grid_input_energy": {
            (None, HW_VERSION_2, 0): 0.1,      # FW 0-153: raw × 10 = Wh (÷0.1)
            (None, HW_VERSION_2, 154): 0.01,   # FW 154+: raw × 100 = Wh (÷0.01)
            (None, HW_VERSION_3, 0): 1.0,      # FW 0+: raw value in Wh
            ("VenusD", HW_VERSION_2, 0): 1.0,
        },

        # Grid export energy from ES.GetStatus, [Wh] per spec.
        "total_grid_output_energy": {
            (None, HW_VERSION_2, 0): 0.1,      # FW 0-153: raw × 10 = Wh (÷0.1)
            (None, HW_VERSION_2, 154): 0.01,   # FW 154+: raw × 100 = Wh (÷0.01)
            (None, HW_VERSION_3, 0): 1.0,      # FW 0+: raw value in Wh
            ("VenusD", HW_VERSION_2, 0): 1.0,
        },

        # Load energy from ES.GetStatus, [Wh] per spec.
        "total_load_energy": {
            (None, HW_VERSION_2, 0): 0.1,      # FW 0-153: raw × 10 = Wh (÷0.1)
            (None, HW_VERSION_2, 154): 0.01,   # FW 154+: raw × 100 = Wh (÷0.01)
            (None, HW_VERSION_3, 0): 1.0,      # FW 0+: raw value in Wh
            ("VenusD", HW_VERSION_2, 0): 1.0,
        },

        # Battery voltage (V) - ALWAYS scaled by 100
        "bat_voltage": {
            (None, HW_VERSION_2, 0): 100.0,    # All FW: raw in centi-V (÷100)
            (None, HW_VERSION_3, 0): 100.0,    # All FW: raw in centi-V (÷100)
        },

        # Battery current (A) - ALWAYS scaled by 100
        "bat_current": {
            (None, HW_VERSION_2, 0): 100.0,    # All FW: raw in centi-A (÷100)
            (None, HW_VERSION_3, 0): 100.0,    # All FW: raw in centi-A (÷100)
        },
    }

    def __init__(self, device_model: str, firmware_version: int) -> None:
        """Initialize compatibility matrix for a specific device.

        Args:
            device_model: Full device model string (e.g., "VenusE", "VenusE 3.0")
            firmware_version: Firmware version number (e.g., 139, 154, 200)
        """
        self.device_model = device_model
        self.firmware_version = firmware_version
        self.hardware_version = parse_hardware_version(device_model)
        self.base_model = get_base_model(device_model)

        _LOGGER.debug(
            "Initialized compatibility matrix: model=%s, base=%s, hw=%s, fw=%d",
            device_model, self.base_model, self.hardware_version, firmware_version
        )

    def scale_value(self, value: float | None, field: str) -> float | None:
        """Scale a raw API value based on model, firmware, and hardware version.

        Lookup logic:
        1. Filter to entries matching this hardware version.
        2. Prefer entries that name our base model; fall back to wildcard
           (model=None) entries only if no model-specific row applies.
        3. Among the chosen tier, pick the highest firmware version <= ours.

        Args:
            value: Raw value from API
            field: Field name (e.g., "bat_temp", "bat_power")

        Returns:
            Scaled value in correct units, or None if input is None.
            If no scaling is defined, returns the raw value unchanged (default 1.0).
        """
        if value is None:
            return None

        if field not in self.SCALING_MATRIX:
            return value

        scaling_map = self.SCALING_MATRIX[field]

        # Entries that match our hardware version, partitioned by whether they
        # are model-specific or wildcard. Each entry is reduced to (fw, divisor).
        model_specific: list[tuple[int, float]] = []
        wildcard: list[tuple[int, float]] = []
        for (model, hw_ver, fw_ver), divisor in scaling_map.items():
            if hw_ver != self.hardware_version:
                continue
            if model is None:
                wildcard.append((fw_ver, divisor))
            elif model == self.base_model:
                model_specific.append((fw_ver, divisor))

        # Prefer model-specific tier when it has a row applicable to our firmware.
        for tier in (model_specific, wildcard):
            applicable = [(fw, d) for fw, d in tier if fw <= self.firmware_version]
            if applicable:
                _, divisor = max(applicable, key=lambda x: x[0])
                return value / divisor

        _LOGGER.debug(
            "No scaling entries for %s with model=%s, hw=%s, fw=%d; using raw value",
            field, self.base_model, self.hardware_version, self.firmware_version,
        )
        return value

    def get_info(self) -> dict[str, Any]:
        """Get compatibility information for diagnostics.

        Returns:
            Dictionary with compatibility details
        """
        return {
            "device_model": self.device_model,
            "base_model": self.base_model,
            "hardware_version": self.hardware_version,
            "firmware_version": self.firmware_version,
        }
