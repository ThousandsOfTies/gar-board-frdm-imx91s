# gar-board-frdm-imx91s

Reusable board component for **NXP FRDM-IMX91S**. A GAR Product pins this repository
alongside its application and gar-tools, and selects `nxp-linux-6.6-spinand`.

The profile owns the existing NXP Linux 6.6/Scarthgap BSP compatibility set,
AArch64 compiler/linker defaults, expansion-header LPI2C4 pins, pinmux tuples,
rail nodes, SPI-NAND partition inventory, USB/UUU transfer and memory settings.
Its inventory is deliberately a documented subset, not the whole board.

`tools/board.py` provides offline profile validation, environment rendering, and
Device Tree overlay generation/build/verification. A caller's policy supplies
`controller`, `frequency_hz`, `pin_group` and `keep_rails`. Policies contain no raw
pinmux tuples. The application, peripheral address, wiring purpose, calibration,
boot-image filenames and write authorization stay in the Product.

```sh
python3 tools/board.py validate
python3 -m unittest discover -s tests -v
python3 tools/board.py render-overlay --policy /path/to/policy.json --output /tmp/header.dtso
```

DTB compilation uses local `dtc/fdtoverlay/fdtget`, with the existing temporary
Debian Docker fallback when needed. No command contacts a board, starts UUU or
builds/downloads an NXP BSP. EULA acceptance, SDK/source caches and firmware/ROM
bytes remain external. New physical-board testing has not been performed for
this repository extraction. Live NAND geometry must still be checked before a
Product authorizes writes through the existing GAR UUU safety gates.

Shared command templates and GAR lifecycle remain in gar-tools. The profile's
`frdm-imx91s-spinand-v1` geometry must agree with that legacy protocol contract.

References: [NXP board overview](https://www.nxp.com/design/design-center/development-boards-and-designs/FRDM-IMX91S),
[NXP Linux BSP DT](https://github.com/nxp-imx/linux-imx/blob/lf-6.6.y/arch/arm64/boot/dts/freescale/imx91-11x11-frdm-imx91s.dts).
