#!/usr/bin/env python3
"""Offline FRDM-IMX91S profile and DTB tools. Never run UUU or access a board."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = "nxp-linux-6.6-spinand"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(profile_name=DEFAULT_PROFILE, root=ROOT):
    root = Path(root).resolve()
    board = read(root / "board.json")
    if board.get("schema_version") != 1 or board["id"] != "frdm-imx91s":
        raise ValueError("Expected FRDM-IMX91S board schema")
    path = (root / board["profiles"][profile_name]).resolve()
    if root not in path.parents:
        raise ValueError("Profile path escapes board repository")
    profile = read(path)
    if profile.get("schema_version") != 1 or profile["board"] != board["id"]:
        raise ValueError("Board/profile identity mismatch")
    if (profile["architecture"], profile["abi"]) != ("aarch64", "gnu"):
        raise ValueError("Unsupported BSP ABI")
    parts = profile["uuu"]["partitions"]
    if (sum(item["size"] for item in parts) != profile["uuu"]["nand_bytes"]
            or len({item["mtd"] for item in parts}) != len(parts)
            or len({item["name"] for item in parts}) != len(parts)):
        raise ValueError("Invalid NAND partition inventory")
    if any(item["size"] <= 0 or item["mtd"] < 0 for item in parts):
        raise ValueError("Invalid NAND partition value")
    if "GAR_IMX91S_NAND_LAYOUT_CONFIRMED" in profile["uuu"]["environment"]:
        raise ValueError("Live NAND confirmation is never a board default")
    return board, profile


def environment(profile):
    values = dict(profile["uuu"]["environment"])
    values.update({item["env"]: str(item["mtd"]) for item in profile["uuu"]["partitions"]})
    values.update(GAR_BOARD_TARGET_CC=profile["toolchain"]["cc"],
                  GAR_BOARD_TARGET_LDFLAGS=profile["toolchain"]["target_ldflags"],
                  GAR_BOARD_ELF_MACHINE=profile["toolchain"]["elf_machine"],
                  GAR_BOARD_BASE_DTB=profile["bsp"]["base_dtb"])
    return values


def validate_policy(profile, policy):
    buses = {bus["controller"]: bus for bus in profile["i2c"]}
    bus = buses.get(policy["controller"])
    if not bus or not 0 < policy["frequency_hz"] <= bus["max_speed_hz"]:
        raise ValueError("I2C policy exceeds board resources")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", policy["pin_group"]):
        raise ValueError("Invalid DT pin group")
    rails = policy["keep_rails"]
    if len(set(rails)) != len(rails) or not set(rails) <= set(profile["rails"]):
        raise ValueError("Unknown or duplicate expansion rail")
    return bus


def render_overlay(profile, policy):
    bus = validate_policy(profile, policy)
    pins = "\n".join("                    " + " ".join(f"0x{value:x}" for value in row) for row in bus["pinmux"])
    text = f'''/dts-v1/;
/plugin/;
/* Generated from the selected board profile and caller's I2C/power policy. */
/ {{
    fragment@0 {{
        target-path = "{bus['pinctrl_node']}";
        __overlay__ {{
            gar_board_i2c_pins: {policy['pin_group']} {{
                fsl,pins = <
{pins}
                >;
            }};
        }};
    }};
    fragment@1 {{
        target-path = "{bus['node']}";
        __overlay__ {{
            clock-frequency = <{policy['frequency_hz']}>;
            pinctrl-names = "default";
            pinctrl-0 = <&gar_board_i2c_pins>;
            status = "okay";
        }};
    }};
'''
    for number, rail in enumerate(policy["keep_rails"], 2):
        text += f'''    fragment@{number} {{
        target-path = "{profile['rails'][rail]['node']}";
        __overlay__ {{ regulator-always-on; }};
    }};
'''
    return text + "};\n"


def verify_dtb(path, profile, policy):
    bus = validate_policy(profile, policy)
    def get(kind, node, property_name):
        return subprocess.check_output(["fdtget", f"-t{kind}", str(path), node, property_name], text=True).strip()
    if get("s", bus["node"], "status") != "okay":
        raise ValueError("Merged DTB has disabled I2C")
    if get("i", bus["node"], "clock-frequency") != str(policy["frequency_hz"]):
        raise ValueError("Merged DTB frequency differs from policy")
    node = bus["pinctrl_node"] + "/" + policy["pin_group"]
    expected = " ".join(f"{value:x}" for row in bus["pinmux"] for value in row)
    if get("x", node, "fsl,pins") != expected:
        raise ValueError("Merged DTB pinmux differs from board profile")
    # Verify that the controller actually uses this pin group.
    if get("x", bus["node"], "pinctrl-0") != get("x", node, "phandle"):
        raise ValueError("Merged I2C controller does not reference the selected pin group")
    for rail in policy["keep_rails"]:
        subprocess.run(["fdtget", str(path), profile["rails"][rail]["node"], "regulator-always-on"], check=True, capture_output=True)


def build_dtb(base, output, profile_name, policy, *, overlay=None, no_docker=False):
    _, profile = load(profile_name)
    validate_policy(profile, policy)
    base, output = Path(base).resolve(), Path(output).resolve()
    if not base.is_file() or base == output:
        raise ValueError("Base DTB must exist and must not be overwritten")
    if overlay is not None and not Path(overlay).is_file():
        raise ValueError("Custom overlay is missing")
    with tempfile.TemporaryDirectory(prefix="gar-imx91s-dtb-") as directory:
        work = Path(directory)
        source = work / "overlay.dtso"
        source.write_text(Path(overlay).read_text(encoding="utf-8") if overlay else render_overlay(profile, policy), encoding="utf-8")
        merged = work / "merged.dtb"
        if all(shutil.which(tool) for tool in ("dtc", "fdtoverlay", "fdtget")):
            subprocess.run(["dtc", "-@", "-I", "dts", "-O", "dtb", "-o", str(work / "overlay.dtbo"), str(source)], check=True)
            subprocess.run(["fdtoverlay", "-i", str(base), "-o", str(merged), str(work / "overlay.dtbo")], check=True)
            verify_dtb(merged, profile, policy)
        elif not no_docker and shutil.which("docker"):
            (work / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
            subprocess.run([
                "docker", "run", "--rm", "--volume", f"{ROOT}:/board:ro",
                "--volume", f"{base}:/input/base.dtb:ro", "--volume", f"{work}:/output",
                "debian:bookworm-slim", "sh", "-euc",
                'apt-get update >/dev/null && apt-get install --yes --no-install-recommends device-tree-compiler python3 >/dev/null; exec "$@"',
                "sh", "python3", "/board/tools/board.py", "--profile", profile_name,
                "build-dtb", "--no-docker", "--base", "/input/base.dtb", "--output", "/output/merged.dtb",
                "--overlay", "/output/overlay.dtso", "--policy", "/output/policy.json",
            ], check=True)
        else:
            raise ValueError("Install device-tree-compiler tools or provide Docker for the existing DTB build fallback")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(merged, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("validate")
    commands.add_parser("environment")
    for action in ("render-overlay", "build-dtb"):
        command = commands.add_parser(action)
        command.add_argument("--policy", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if action == "build-dtb":
            command.add_argument("--base", type=Path, required=True)
            command.add_argument("--overlay", type=Path)
            command.add_argument("--no-docker", action="store_true")
    args = parser.parse_args()
    board, profile = load(args.profile)
    if args.action == "validate":
        print(json.dumps({"board": board["id"], "profile": args.profile, "architecture": profile["architecture"]}, indent=2))
    elif args.action == "environment":
        for key, value in environment(profile).items():
            print(f"export {key}={shlex.quote(value)}")
    elif args.action == "render-overlay":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_overlay(profile, read(args.policy)), encoding="utf-8")
    else:
        print(build_dtb(args.base, args.output, args.profile, read(args.policy), overlay=args.overlay, no_docker=args.no_docker))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"FRDM-IMX91S board: {error}") from error
