# Board component boundary

Own board/BSP identity, ABI/compiler defaults, resource inventory, pinmux/register
tuples, rail nodes, NAND geometry and UUU transfer facts. Do not add Product names,
servo roles, PCA9685 addresses/channels, calibration, app behavior or artifacts.
Caller policy chooses I2C frequency and which rails stay on; this repo supplies
capabilities and renders/verifies the DT overlay. Shared GAR UUU command templates,
safety gates and lifecycle remain in gar-tools. No UUU invocation or device access
is allowed in offline validation. Never bake live NAND confirmation into a profile.
BSP/ROM/SDK binaries, EULA acceptance, USB identities and local build caches are
external. Preserve the supported BSP compatibility set; do not upgrade it merely
while reorganizing repositories.
