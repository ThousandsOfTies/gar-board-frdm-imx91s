import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('board_tools', ROOT / 'tools/board.py')
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)

POLICY = {'controller': 'LPI2C4', 'frequency_hz': 100000,
          'pin_group': 'header-i2c-pins', 'keep_rails': ['exp-3v3', 'exp-5v']}
BASE = '''/dts-v1/;
/ {
 compatible = "fsl,imx91-11x11-frdm";
 regulator-exp-3v3 {};
 regulator-exp-5v {};
 soc@0 {
  bus@42000000 { i2c@42540000 { status = "disabled"; }; };
  bus@44000000 { pinctrl@443c0000 {}; };
 };
};
'''


class BoardTests(unittest.TestCase):
    def test_profile_is_complete_without_an_application(self):
        identity, profile = board.load()
        self.assertEqual('frdm-imx91s', identity['id'])
        self.assertEqual({'SDA': '3', 'SCL': '5'}, profile['i2c'][0]['pins'])
        self.assertEqual('AArch64', profile['toolchain']['elf_machine'])
        self.assertEqual(268435456, sum(p['size'] for p in profile['uuu']['partitions']))
        self.assertNotIn('GAR_IMX91S_NAND_LAYOUT_CONFIRMED', board.environment(profile))
        self.assertNotIn('gar-servo-pet', json.dumps(profile))

    def test_caller_policies_do_not_modify_each_other(self):
        _, profile = board.load()
        first = board.render_overlay(profile, POLICY)
        second = board.render_overlay(profile, {**POLICY, 'frequency_hz': 50000, 'keep_rails': []})
        self.assertIn('clock-frequency = <100000>', first)
        self.assertIn('clock-frequency = <50000>', second)
        self.assertIn('regulator-always-on', first)
        self.assertNotIn('regulator-always-on', second)
        self.assertEqual(first, board.render_overlay(profile, POLICY))

    def test_invalid_policy_cannot_inject_raw_device_tree(self):
        _, profile = board.load()
        for changes in ({'controller': 'LPI2C99'}, {'frequency_hz': 400000},
                        {'pin_group': 'invalid; node'}, {'keep_rails': ['unknown']}):
            with self.assertRaises(ValueError):
                board.render_overlay(profile, {**POLICY, **changes})

    @unittest.skipUnless(all(shutil.which(tool) for tool in ('dtc', 'fdtoverlay', 'fdtget')), 'device-tree-compiler missing')
    def test_real_dtb_compilation_and_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'base.dts').write_text(BASE)
            subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(root / 'base.dtb'), str(root / 'base.dts')], check=True, capture_output=True)
            output = board.build_dtb(root / 'base.dtb', root / 'out.dtb', board.DEFAULT_PROFILE, POLICY, no_docker=True)
            _, profile = board.load()
            board.verify_dtb(output, profile, POLICY)
            with self.assertRaises(ValueError):
                board.build_dtb(root / 'base.dtb', root / 'base.dtb', board.DEFAULT_PROFILE, POLICY, no_docker=True)
            (root / 'bad.dtso').write_text(board.render_overlay(profile, {**POLICY, 'frequency_hz': 50000}))
            with self.assertRaisesRegex(ValueError, 'frequency'):
                board.build_dtb(root / 'base.dtb', root / 'bad.dtb', board.DEFAULT_PROFILE, POLICY, overlay=root / 'bad.dtso', no_docker=True)
            self.assertFalse((root / 'bad.dtb').exists())


if __name__ == '__main__':
    unittest.main()
