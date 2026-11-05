from decimal import Decimal as D
from fractions import Fraction as F
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from battery import load_scenario, screen


ROOT = Path(__file__).resolve().parents[1]


def example(name="baseline"):
    return load_scenario(ROOT / "examples" / f"{name}.json")


class BatteryTests(unittest.TestCase):
    def test_baseline_against_hand_calculation(self):
        r = screen(example())
        for key, value in {
            "mission_minutes": "120", "average_w": "45", "energy_wh": "90",
            "budget_wh": "103.68", "energy_margin_wh": "13.68",
            "load_v": "21.2", "voltage_margin_v": "0.2",
        }.items():
            self.assertEqual(r[key], D(value), key)
        self.assertAlmostEqual(r["minimum_nominal_ah"], D(125) / 24)
        self.assertTrue(r["energy_ok"] and r["voltage_ok"])

    def test_energy_and_voltage_fail_independently(self):
        sag = screen(example("sag-limited"))
        self.assertEqual((sag["energy_ok"], sag["voltage_ok"], sag["load_v"]),
                         (True, False, D("20.6")))
        energy = screen(example("energy-limited"))
        self.assertEqual((energy["energy_ok"], energy["voltage_ok"], energy["budget_wh"]),
                         (False, True, D("86.4")))

    def test_exact_threshold_and_rounding_are_separate(self):
        s = example()
        s["pack"] |= {"nominal_v": D(20), "capacity_ah": D(5), "usable_fraction": D(1)}
        s["peak"] |= {"open_circuit_v": D("22.8")}
        r = screen(s)
        self.assertTrue(r["energy_ok"] and r["voltage_ok"])
        s["phases"][0]["average_w"] += D("0.001")
        s["peak"]["open_circuit_v"] -= D("0.001")
        r = screen(s)
        self.assertFalse(r["energy_ok"] or r["voltage_ok"])

    def test_splitting_a_phase_preserves_the_budget(self):
        s = example()
        baseline = screen(s)
        first = s["phases"].pop(0)
        s["phases"] += [first | {"minutes": D(15)}, first | {"minutes": D(45)}]
        self.assertEqual(screen(s), baseline)

    def test_invalid_units_shape_and_values(self):
        for section, key, value in [
            ("peak", "path_ohm", D(-1)), ("peak", "current_a", D("Infinity")),
            ("pack", "reserve_fraction", D(1)), ("pack", "nominal_v", "24"),
            ("pack", "usable_fraction", True), ("pack", "capacity_ah", D(0)),
            ("pack", "usable_fraction", D("0.0000001")), ("peak", "wrong_unit", D(1)),
        ]:
            with self.subTest(section=section, key=key, value=value):
                s = example()
                s[section][key] = value
                with self.assertRaises(ValueError):
                    screen(s)
        s = example()
        s["phases"] = []
        with self.assertRaisesRegex(ValueError, "one to 100"):
            screen(s)

    def test_outside_model_and_no_load(self):
        s = example()
        s["peak"]["path_ohm"] = D(2)
        self.assertTrue(screen(s)["outside_linear_model"])
        s["peak"]["current_a"] = D(0)
        s["phases"] = [{"name": "Off", "minutes": D(1), "average_w": D(0)}]
        r = screen(s)
        self.assertEqual(r["energy_wh"], 0)
        self.assertEqual(r["load_v"], 23)
        self.assertTrue(r["energy_ok"] and r["voltage_ok"])

    def test_randomized_independent_fraction_oracle(self):
        rng = random.Random(249)
        for case in range(160):
            s = example()
            pairs = [(rng.randint(1, 90), rng.randint(0, 300)) for _ in range(rng.randint(1, 8))]
            s["phases"] = [{"name": str(i), "minutes": D(t), "average_w": D(p)}
                           for i, (t, p) in enumerate(pairs)]
            capacity = rng.randint(1, 20)
            resistance_mohm = rng.randint(0, 400)
            current = rng.randint(0, 50)
            s["pack"]["capacity_ah"] = D(capacity)
            s["peak"] |= {"current_a": D(current), "path_ohm": D(resistance_mohm) / 1000}
            # Exact rational reference: sum phase energies after converting every duration to hours.
            energy = sum((F(minutes, 60) * watts for minutes, watts in pairs), F(0))
            spendable = F(24 * capacity * 72, 100)
            voltage = F(23) - F(resistance_mohm * current, 1000)
            r = screen(s)
            with self.subTest(case=case):
                self.assertEqual(r["energy_ok"], energy <= spendable)
                self.assertEqual(r["voltage_ok"], voltage >= 21)
                self.assertAlmostEqual(float(r["energy_wh"]), float(energy), places=9)
                self.assertEqual(F(r["load_v"]), voltage)

    def test_cli_exit_codes(self):
        for name in ("baseline", "sag-limited", "energy-limited"):
            result = subprocess.run([sys.executable, "battery.py", f"examples/{name}.json"],
                                    cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Screen only.", result.stdout)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.json"
            path.write_text('{"pack": {}, "pack": {}}', encoding="utf-8")
            result = subprocess.run([sys.executable, "battery.py", str(path)],
                                    cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("duplicate JSON field", result.stderr)
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
