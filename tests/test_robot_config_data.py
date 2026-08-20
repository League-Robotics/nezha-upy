"""Offline validation tests for the one-time-copied robot config data.

See data/README.md for provenance and the two deviations applied from
the source (gopiv.json's wiring fix, tovez.json's radio channel).

Schema note: `data/robot_config.schema.json` doesn't yet validate the
per-robot files as whole documents -- they still carry fields
(`additionalProperties: false` groups/top level) the schema doesn't
model. So this module checks the schema's field-level type/range
constraints group by group, for whichever fields are actually present,
instead of a whole-document `jsonschema.validate()` call.
"""

import json
import pathlib
import unittest

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

ROBOT_FILES = ["tovez.json", "tovez_nocal.json", "gopiv.json", "togov.json", "zetuv.json"]
ALL_JSON_FILES = ROBOT_FILES + ["robot_config.schema.json", "active_robot.json"]


def load(name):
    with open(DATA_DIR / name) as f:
        return json.load(f)


class TestFilesExistAndParse(unittest.TestCase):
    def test_all_files_exist(self):
        for name in ALL_JSON_FILES:
            with self.subTest(name=name):
                self.assertTrue((DATA_DIR / name).is_file(), f"missing {name}")

    def test_all_files_parse_as_json(self):
        for name in ALL_JSON_FILES:
            with self.subTest(name=name):
                load(name)  # raises json.JSONDecodeError on malformed input


class TestSchemaFieldConstraints(unittest.TestCase):
    """Hand-rolled per-field type/range check against the schema's own
    definitions. See module docstring for why this replaces a
    whole-document jsonschema.validate() call."""

    @classmethod
    def setUpClass(cls):
        cls.schema = load("robot_config.schema.json")

    def _definition_for_group(self, group_name):
        group_ref = self.schema["properties"].get(group_name)
        if group_ref is None:
            return None  # group not modeled by schema yet (known gap)
        def_name = group_ref["$ref"].rsplit("/", 1)[-1]
        return self.schema["definitions"][def_name]

    def _assert_type(self, value, spec):
        json_type = spec.get("type")
        if json_type == "integer":
            # JSON Schema "integer" allows a whole-numbered float (60.0),
            # matching jsonschema.Draft7Validator -- only reject
            # non-numbers, bools, and genuine fractions.
            self.assertNotIsInstance(value, bool)
            self.assertIsInstance(value, (int, float))
            self.assertEqual(value, int(value))
        elif json_type == "number":
            self.assertIsInstance(value, (int, float))
            self.assertNotIsInstance(value, bool)
        elif json_type == "string":
            self.assertIsInstance(value, str)
        elif json_type == "boolean":
            self.assertIsInstance(value, bool)

    def _assert_range(self, value, spec):
        if isinstance(value, bool):
            return  # bools aren't subject to numeric range checks
        if "minimum" in spec and isinstance(value, (int, float)):
            self.assertGreaterEqual(value, spec["minimum"])
        if "maximum" in spec and isinstance(value, (int, float)):
            self.assertLessEqual(value, spec["maximum"])

    def test_robot_files_match_schema_field_constraints(self):
        checked_any_field = False
        for name in ROBOT_FILES:
            data = load(name)
            for group_name, group_data in data.items():
                if group_name.startswith("_") or not isinstance(group_data, dict):
                    continue
                definition = self._definition_for_group(group_name)
                if definition is None:
                    continue  # group not modeled by schema yet (known gap)
                props = definition.get("properties", {})
                for key, value in group_data.items():
                    if key.startswith("_"):
                        continue  # free-text documentation field
                    spec = props.get(key)
                    if spec is None:
                        continue  # field not modeled by schema yet (known gap)
                    with self.subTest(robot=name, group=group_name, field=key):
                        self._assert_type(value, spec)
                        self._assert_range(value, spec)
                        checked_any_field = True
        self.assertTrue(
            checked_any_field,
            "no fields were checked against the schema -- the schema "
            "or the per-robot files likely changed shape",
        )


class TestGopivWiringFix(unittest.TestCase):
    """gopiv.json must carry the true wiring: left_port 2, right_port
    1, fwd_sign_left 1, fwd_sign_right -1."""

    def test_gopiv_true_wiring(self):
        motors = load("gopiv.json")["motors"]
        self.assertEqual(motors["left_port"], 2)
        self.assertEqual(motors["right_port"], 1)
        self.assertEqual(motors["fwd_sign_left"], 1)
        self.assertEqual(motors["fwd_sign_right"], -1)


class TestTovezRadioChannel(unittest.TestCase):
    """tovez.json must specify radio channel 3."""

    def test_tovez_radio_channel_3(self):
        connection = load("tovez.json")["connection"]
        self.assertEqual(connection["radio_channel"], 3)


class TestZetuvRadioChannel(unittest.TestCase):
    """zetuv.json must specify radio channel 3, matching tovez's bench
    convention."""

    def test_zetuv_radio_channel_3(self):
        connection = load("zetuv.json")["connection"]
        self.assertEqual(connection["radio_channel"], 3)


class TestZetuvWiring(unittest.TestCase):
    """zetuv.json's motors block must carry BENCH-MEASURED
    left_port/right_port/fwd_sign_left/fwd_sign_right values, not
    tovez_nocal.json's inherited placeholders."""

    def test_zetuv_motors_wiring_measured(self):
        motors = load("zetuv.json")["motors"]
        self.assertIn("left_port", motors, "left_port must be a measured, not omitted, field")
        self.assertIn("right_port", motors, "right_port must be a measured, not omitted, field")
        self.assertIn(motors["left_port"], (1, 2, 3, 4))
        self.assertIn(motors["right_port"], (1, 2, 3, 4))
        self.assertNotEqual(motors["left_port"], motors["right_port"])
        self.assertIn(motors["fwd_sign_left"], (-1, 1))
        self.assertIn(motors["fwd_sign_right"], (-1, 1))


class TestNoWifiCredentials(unittest.TestCase):
    """Guard against accidentally-copied secrets."""

    FORBIDDEN_SUBSTRINGS = (
        "password",
        "psk",
        "ssid",
        "wifi_pass",
        "secret",
        "api_key",
        "token",
    )

    def test_no_credential_keys_present(self):
        for name in ALL_JSON_FILES:
            text = (DATA_DIR / name).read_text().lower()
            for forbidden in self.FORBIDDEN_SUBSTRINGS:
                with self.subTest(name=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
