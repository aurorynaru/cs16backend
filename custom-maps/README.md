# Custom maps supplied by the operator

Included map selector: `CS16_START_MAP=cs_deathmatch`.

The operator supplied `cs_deathmatch_2.rar` under assets/FX_CS16Local. Its map's
actual filename is `cs_deathmatch.bsp` (without `_2`). The BSP is GoldSrc version
30 and is copied byte-for-byte into `cstrike/maps/`, together with its supplied
NAV file. Original README: `notices/cs_deathmatch-Readme.txt`. The redundant
`.bsp.ztmp` transfer cache is omitted. Bots and NAV compatibility are not added
or verified by including that file.

The map contains six CT and six T spawn entities and two hostages. A 12-player
limit is a sensible initial setting. Its name does not change classic CS rules
into automatic-respawn deathmatch. It uses 15 external textures resolved from
the stock WADs; the build packer checks those against the browser bundle.

The other supplied archive, `fy_pool_day_reloaded.zip`, contains a Source BSP
with magic `VBSP` and version 20. That file is incompatible with this GoldSrc
client/server and is not copied here. Obtain the Counter-Strike 1.6 version
before adding it. The original user archives remain unchanged.

## Packaging

The Docker content stage runs `scripts/package_maps.py` to validate these
assets, copy identical bytes into the native server paths and browser
`gamefiles.zip`, and generate a SHA-256 bundle identity. The protected asset
route publishes that identity as its ETag; the existing client checks it before
reusing cached game data. A new map release can require another full game-data
download on first join.

Additional maps need GoldSrc BSP 30 files and their complete dependency files.
Place maps under `cstrike/maps`, WADs in `cstrike/`, and associated assets in
their original models/sound/sprites/gfx/overviews directories. The packer rejects
scripts, binaries, symlinks, stock-file overwrites, malformed BSP headers and
unresolved static BSP texture/model/sound/sprite references. Its checks do not
prove every possible game/plugin/resource dependency or map rendering behavior.

## Local checks

Four map-packaging tests passed, including the actual supplied map/NAV with
synthetic stock-WAD fixtures, unchanged base ZIP, byte equality and invalid input
rejection. A separate run checked the actual pinned stock server/client WADs,
built the complete browser bundle and queried a real native server loaded with
cs_deathmatch through the TCP gateway. Evidence is in BLD-011. That check used
the historical cached native runtime; the Docker build retains the separately
tested BLD-010 repair. Full new Docker/Railway execution and browser map rendering
remain pending.
