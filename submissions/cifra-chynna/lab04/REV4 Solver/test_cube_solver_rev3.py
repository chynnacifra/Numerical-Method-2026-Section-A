import os
import tempfile
import unittest

import cube_solver_rev3 as solver


class Rev4RequirementsTests(unittest.TestCase):
    def test_nine_load_cases_exist(self):
        self.assertEqual(len(solver.REV4_ARCHITECTURE["load_cases"]), 9)

    def test_roof_dead_total_is_integrated(self):
        self.assertEqual(solver.REV4_LOAD_VALIDATION[2]["computed_total_kN"], 120.0)

    def test_roof_live_total_is_integrated(self):
        self.assertEqual(solver.REV4_LOAD_VALIDATION[3]["computed_total_kN"], 72.0)

    def test_nodal_case_totals(self):
        self.assertEqual(solver.REV4_LOAD_VALIDATION[5]["computed_total_kN"], 10.0)
        self.assertEqual(solver.REV4_LOAD_VALIDATION[8]["computed_total_kN"], 15.0)

    def test_diaphragm_dofs(self):
        self.assertEqual(solver.REV4_ROOF_DIAPHRAGM.degrees_of_freedom, ["UX", "UZ", "RY"])

    def test_temperature_case_units_and_change(self):
        case = solver.REV4_ARCHITECTURE["load_cases"][8]
        self.assertEqual(case.category, "Temperature")
        self.assertTrue(all(load.temperature_change == 15.0 for load in case.loads))
        self.assertTrue(all(load.unit == "degC" for load in case.loads))

    def test_temperature_restrained_and_partial_states(self):
        states = {item["restraint_state"] for item in solver.REV4_TEMPERATURE_VERIFICATION["members"].values()}
        self.assertEqual(states, {"fully restrained", "free", "partially restrained / indeterminate"})

    def test_temperature_axial_rigidity_and_restrained_force(self):
        values = solver.REV4_TEMPERATURE_VERIFICATION["members"]
        fully_restrained = [item for item in values.values() if item["restraint_state"] == "fully restrained"]
        self.assertTrue(fully_restrained)
        self.assertGreater(fully_restrained[0]["axial_rigidity_kN"], 0.0)
        self.assertLess(fully_restrained[0]["thermal_force_kN"], 0.0)

    def test_temperature_strain(self):
        item = next(iter(solver.REV4_TEMPERATURE_VERIFICATION["members"].values()))
        self.assertAlmostEqual(item["thermal_strain"], 1.755e-4, places=10)

    def test_temperature_free_expansion(self):
        item = next(iter(solver.REV4_TEMPERATURE_VERIFICATION["members"].values()))
        self.assertAlmostEqual(item["free_expansion_mm"], 1.053, places=6)

    def test_temperature_vector_is_nonempty_and_self_equilibrating(self):
        vector = solver.assemble_rev4_temperature_vector()
        self.assertTrue(vector)
        for component in range(3):
            self.assertAlmostEqual(sum(values[component] for values in vector.values()), 0.0, places=6)

    def test_combination_assembly_uses_referenced_cases(self):
        loads = solver.assemble_rev4_combination_loads(1)
        expected = {}
        for case_id, factor in {1: 1.4, 2: 1.4, 4: 1.4}.items():
            for node_id, values in solver.assemble_rev4_case_to_solver_loads(case_id).items():
                expected[node_id] = [
                    current + factor * value
                    for current, value in zip(expected.get(node_id, [0.0] * 6), values)
                ]
        expected = {node_id: values for node_id, values in expected.items() if any(abs(value) > 1e-9 for value in values)}
        self.assertEqual(loads, expected)

    def test_mechanical_case_solves(self):
        result = solver.solve_rev4_case(2)
        self.assertEqual(result["case_name"], "ROOF DEAD")
        self.assertGreaterEqual(result["analysis"]["max_disp"], 0.0)

    def test_viewer_renders(self):
        model = solver.build_model()
        with tempfile.TemporaryDirectory() as folder:
            output = os.path.join(folder, "rev4_view.png")
            solver.plot_structural_model(model, output, show_grid=False)
            self.assertTrue(os.path.isfile(output))
            self.assertGreater(os.path.getsize(output), 0)


def _case_registry_test(case_id):
    def test(self):
        case = next(item for item in solver.REV4_ARCHITECTURE["load_cases"] if item.id == case_id)
        self.assertEqual(case.id, case_id)
        self.assertTrue(case.name)
        self.assertTrue(case.category)
    return test


def _combination_structure_test(combination_id):
    def test(self):
        combination = next(item for item in solver.REV4_ARCHITECTURE["load_combinations"] if item.id == combination_id)
        self.assertTrue(combination.factors)
        self.assertIn(combination.design_method, {"LRFD", "ASD"})
        self.assertTrue(all(case_id in range(1, 10) for case_id in combination.factors))
    return test


def _combination_assembly_test(combination_id):
    def test(self):
        combination = next(item for item in solver.REV4_ARCHITECTURE["load_combinations"] if item.id == combination_id)
        expected = {}
        for case_id, factor in combination.factors.items():
            for node_id, values in solver.assemble_rev4_case_to_solver_loads(case_id).items():
                expected[node_id] = [
                    current + factor * value
                    for current, value in zip(expected.get(node_id, [0.0] * 6), values)
                ]
        expected = {node_id: values for node_id, values in expected.items() if any(abs(value) > 1e-9 for value in values)}
        self.assertEqual(solver.assemble_rev4_combination_loads(combination_id), expected)
    return test


def _glyph_case_test(case_id):
    def test(self):
        glyphs = solver.build_rev4_case_glyphs(case_id)
        expected_count = 12 if case_id == 1 else len(solver.REV4_ARCHITECTURE["load_cases"][case_id - 1].loads)
        self.assertEqual(len(glyphs), expected_count)
    return test


def _audit_test(index):
    def test(self):
        self.assertEqual(len(solver.REV4_ARCHITECTURE["load_cases"]), 9)
        self.assertEqual(len(solver.REV4_ARCHITECTURE["load_combinations"]), 30)
        self.assertTrue(solver.REV4_MODEL_LINKAGE_VALIDATION["valid"])
        self.assertTrue(solver.REV4_SOLVER_COMPATIBILITY_VALIDATION["valid"])
        self.assertEqual(solver.REV4_TEMPERATURE_VERIFICATION["net_force_kN"], 0.0)
    return test


for _case_id in range(1, 10):
    setattr(Rev4RequirementsTests, f"test_case_registry_{_case_id:02d}", _case_registry_test(_case_id))
    setattr(Rev4RequirementsTests, f"test_case_glyphs_{_case_id:02d}", _glyph_case_test(_case_id))
for _combination_id in range(1, 31):
    setattr(Rev4RequirementsTests, f"test_combination_structure_{_combination_id:02d}", _combination_structure_test(_combination_id))
    setattr(Rev4RequirementsTests, f"test_combination_assembly_{_combination_id:02d}", _combination_assembly_test(_combination_id))
for _index in range(5):
    setattr(Rev4RequirementsTests, f"test_audit_invariants_{_index:02d}", _audit_test(_index))


if __name__ == "__main__":
    unittest.main()
