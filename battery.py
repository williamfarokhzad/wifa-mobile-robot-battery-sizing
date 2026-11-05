"""Battery terminal energy budget and a separate lumped voltage sag screen."""

import argparse
from decimal import Decimal, DecimalException, ROUND_HALF_UP
import json
from pathlib import Path
import sys

D = Decimal


def fields(obj, names, where):
    if not isinstance(obj, dict) or obj.keys() != set(names.split()):
        raise ValueError(f"{where}: expected exactly these fields: {names}")
    return obj


def number(value, name, lo=0, hi=1_000_000):
    if (not isinstance(value, Decimal) or not value.is_finite()
            or not lo <= value <= hi or value.as_tuple().exponent < -6):
        raise ValueError(f"{name}: enter a JSON number from {lo} to {hi} with at most six decimal places")
    return value


def screen(data):
    """Validate one JSON scenario and return unrounded values and screen flags."""
    fields(data, "phases pack peak", "scenario")
    phases = data["phases"]
    if not isinstance(phases, list) or not 1 <= len(phases) <= 100:
        raise ValueError("phases: supply one to 100 sequential mission phases")
    watt_minutes = D(0)
    mission_minutes = D(0)
    for i, phase in enumerate(phases, 1):
        where = f"phase {i}"
        fields(phase, "name minutes average_w", where)
        if not isinstance(phase["name"], str) or not phase["name"].strip():
            raise ValueError(f"{where}: supply a name")
        duration = number(phase["minutes"], f"{where} minutes", D("0.000001"), 10_000)
        power = number(phase["average_w"], f"{where} average_w", 0, 100_000)
        mission_minutes += duration
        watt_minutes += power * duration

    pack = fields(data["pack"], "nominal_v capacity_ah usable_fraction reserve_fraction", "pack")
    nominal = number(pack["nominal_v"], "nominal_v", 1, 1000)
    capacity = number(pack["capacity_ah"], "capacity_ah", D("0.001"), 10_000)
    usable = number(pack["usable_fraction"], "usable_fraction", D("0.000001"), 1)
    reserve = number(pack["reserve_fraction"], "reserve_fraction", 0, D("0.999999"))
    budget_fraction = usable * (1 - reserve)
    budget = nominal * capacity * budget_fraction

    peak = fields(data["peak"], "open_circuit_v current_a path_ohm min_load_v", "peak")
    ocv = number(peak["open_circuit_v"], "open_circuit_v", 1, 1000)
    current = number(peak["current_a"], "current_a", 0, 1000)
    path = number(peak["path_ohm"], "path_ohm", 0, 100)
    minimum = number(peak["min_load_v"], "min_load_v", 1, 1000)
    load = ocv - current * path
    return {
        "mission_minutes": mission_minutes,
        "average_w": watt_minutes / mission_minutes,
        "energy_wh": watt_minutes / 60,
        "budget_wh": budget,
        "minimum_nominal_ah": watt_minutes / (60 * nominal * budget_fraction),
        "energy_margin_wh": (60 * budget - watt_minutes) / 60,
        "load_v": load,
        "voltage_margin_v": load - minimum,
        "energy_ok": watt_minutes <= budget * 60,
        "voltage_ok": load >= minimum,
        "outside_linear_model": load <= 0,
    }


def load_scenario(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), parse_int=D, parse_float=D,
                      parse_constant=lambda value: D(value), object_pairs_hook=unique_pairs)


def format_number(value):
    rounded = value.quantize(D("0.01"), rounding=ROUND_HALF_UP)
    return format(abs(rounded) if not rounded else rounded, ".2f")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    args = parser.parse_args(argv)
    try:
        result = screen(load_scenario(args.scenario))
    except (OSError, ValueError, DecimalException) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2

    def show(key):
        return format_number(result[key])

    print(f"Mission: {show('mission_minutes')} min at {show('average_w')} W average")
    print(f"Energy: {show('energy_wh')} Wh demand / {show('budget_wh')} Wh budget "
          f"(margin {show('energy_margin_wh')} Wh): {'PASS' if result['energy_ok'] else 'FAIL'}")
    print(f"Minimum nominal capacity for energy: {show('minimum_nominal_ah')} Ah (rounded)")
    if result["outside_linear_model"]:
        print("Voltage: model predicts a nonpositive load voltage; input is outside the linear screen: FAIL")
    else:
        print(f"Voltage: {show('load_v')} V at load (margin {show('voltage_margin_v')} V): "
              f"{'PASS' if result['voltage_ok'] else 'FAIL'}")
    print("Screen only. No hardware or battery protection was tested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
