"""Merge validated custom GoldSrc assets into server paths and the browser ZIP.

Uses only the Python standard library. It preserves the base archive, rejects
overwrites and unsupported file types, and publishes a SHA-256 for client cache
validation. BSP/WAD checks are static validation, not an engine rendering test.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import zipfile

ASSET_DIRS = {"maps", "models", "sound", "sprites", "gfx", "overviews"}
ASSET_EXTENSIONS = {".bsp", ".nav", ".res", ".txt", ".wad", ".mdl", ".spr", ".wav", ".mp3", ".tga", ".bmp", ".pcx", ".png", ".jpg"}


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_bsp(data):
    if data[:4] == b"VBSP":
        raise ValueError("Source BSP is incompatible; supply a CS 1.6 / GoldSrc BSP 30 map")
    if len(data) < 124 or struct.unpack_from("<i", data)[0] != 30:
        raise ValueError("Expected a complete GoldSrc BSP version 30 header")
    lumps = []
    for index in range(15):
        offset, size = struct.unpack_from("<ii", data, 4 + index * 8)
        if offset < 0 or size < 0 or offset + size > len(data):
            raise ValueError("BSP lump extends outside the file")
        lumps.append(data[offset:offset + size])
    entities = lumps[0].decode("latin1")
    fields = re.findall(r'"([^"\r\n]+)"\s*"([^"\r\n]*)"', entities)
    wads = []
    references = []
    for key, value in fields:
        if key.lower() == "wad":
            wads.extend(PurePosixPath(part.replace("\\", "/")).name for part in value.split(";") if part)
        elif re.search(r"\.(mdl|wav|mp3|spr)$", value, re.I):
            references.append(value.replace("\\", "/"))
    textures = lumps[2]
    if len(textures) < 4:
        raise ValueError("BSP texture table is absent")
    count = struct.unpack_from("<i", textures)[0]
    if count < 0 or 4 + count * 4 > len(textures):
        raise ValueError("Invalid BSP texture count")
    external = []
    embedded = 0
    for index in range(count):
        offset = struct.unpack_from("<i", textures, 4 + index * 4)[0]
        if offset == -1:
            continue
        if offset < 0 or offset + 40 > len(textures):
            raise ValueError("Invalid BSP miptexture offset")
        name = textures[offset:offset + 16].split(b"\0", 1)[0].decode("latin1")
        if struct.unpack_from("<I", textures, offset + 24)[0] == 0:
            external.append(name)
        else:
            embedded += 1
    return {"bspVersion": 30, "wadNames": sorted(set(wads)), "externalTextures": external,
            "embeddedTextureCount": embedded, "fileReferences": sorted(set(references))}


def wad_textures(stream, size):
    header = stream.read(12)
    if len(header) != 12 or header[:4] not in (b"WAD2", b"WAD3"):
        raise ValueError("Invalid WAD header")
    count, offset = struct.unpack_from("<ii", header, 4)
    if count < 0 or offset < 12 or offset + count * 32 > size:
        raise ValueError("Invalid WAD directory bounds")
    stream.seek(offset)
    directory = stream.read(count * 32)
    if len(directory) != count * 32:
        raise ValueError("Truncated WAD directory")
    return {directory[i * 32 + 16:i * 32 + 32].split(b"\0", 1)[0].decode("latin1").casefold() for i in range(count)}


def collect_assets(custom):
    assets = {}
    for path in sorted(custom.rglob("*")):
        if path.is_symlink():
            raise ValueError("Custom assets cannot be symlinks")
        if not path.is_file():
            continue
        relative = path.relative_to(custom).as_posix()
        parts = PurePosixPath(relative).parts
        if any(part in (".", "..") or ":" in part or "\\" in part or any(ord(c) < 32 for c in part) for part in parts):
            raise ValueError("Invalid custom asset path: " + relative)
        if path.suffix.lower() not in ASSET_EXTENSIONS or (len(parts) == 1 and path.suffix.lower() != ".wad") or (len(parts) > 1 and parts[0] not in ASSET_DIRS):
            raise ValueError("Unsupported custom asset path: " + relative)
        if path.suffix.lower() == ".bsp" and (len(parts) != 2 or parts[0] != "maps" or not re.fullmatch(r"[A-Za-z0-9_]+", path.stem)):
            raise ValueError("BSP must be maps/<map_name>.bsp without spaces")
        key = "cstrike/" + relative
        if key.casefold() in {name.casefold() for name in assets}:
            raise ValueError("Case-colliding custom assets")
        assets[key] = path
    if not any(path.suffix.lower() == ".bsp" for path in assets.values()):
        raise ValueError("No custom BSP maps supplied")
    return assets


def package(base_zip, custom, output):
    base_zip, custom, output = Path(base_zip), Path(custom), Path(output)
    assets = collect_assets(custom)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be empty; existing content was not changed")
    maps = []
    with zipfile.ZipFile(base_zip) as base:
        names = {entry.filename.casefold(): entry for entry in base.infolist()}
        supplied = {name.casefold(): path for name, path in assets.items()}
        for name in supplied:
            if name in names:
                raise ValueError("Custom content would overwrite a stock ZIP entry: " + name)
        wad_cache = {}
        for name, path in assets.items():
            if path.suffix.lower() != ".bsp":
                continue
            info = inspect_bsp(path.read_bytes())
            available = set()
            resolved = []
            for wad in info["wadNames"]:
                match = next((candidate for candidate in ("cstrike/" + wad.casefold(), "valve/" + wad.casefold()) if candidate in supplied or candidate in names), None)
                if match is None:
                    continue  # Old editor WAD lists can contain unused files.
                if match not in wad_cache:
                    if match in supplied:
                        with supplied[match].open("rb") as stream:
                            wad_cache[match] = wad_textures(stream, supplied[match].stat().st_size)
                    else:
                        with base.open(names[match]) as stream:
                            wad_cache[match] = wad_textures(stream, names[match].file_size)
                available.update(wad_cache[match])
                resolved.append(match)
            missing = [texture for texture in info["externalTextures"] if texture.casefold() not in available]
            if missing:
                raise ValueError(path.name + " has unresolved external textures: " + ", ".join(missing))
            for reference in info["fileReferences"]:
                candidates = ["cstrike/" + reference.casefold(), "valve/" + reference.casefold()]
                if reference.lower().endswith((".wav", ".mp3")) and not reference.lower().startswith("sound/"):
                    candidates += ["cstrike/sound/" + reference.casefold(), "valve/sound/" + reference.casefold()]
                if not any(candidate in names or candidate in supplied for candidate in candidates):
                    raise ValueError(path.name + " has an unresolved model/sound/sprite: " + reference)
            maps.append({"name": path.stem, "path": name, **info, "resolvedWads": resolved})
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "gamefiles.zip"
    shutil.copyfile(base_zip, archive)
    records = []
    with zipfile.ZipFile(archive, "a", compression=zipfile.ZIP_DEFLATED) as merged:
        for name, path in assets.items():
            destination = output / "server" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            merged.write(path, arcname=name)
            digest = file_hash(path)
            if file_hash(destination) != digest:
                raise ValueError("Server asset copy differs")
            records.append({"path": name, "bytes": path.stat().st_size, "sha256": digest})
    with zipfile.ZipFile(archive) as merged:
        for record in records:
            with merged.open(record["path"]) as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != record["sha256"]:
                raise ValueError("Client ZIP asset differs from server asset")
    archive_hash = file_hash(archive)
    (output / "gamefiles.sha256").write_text(archive_hash + "\n", encoding="ascii")
    manifest = {"maps": maps, "files": records, "gamefilesSHA256": archive_hash,
                "boundary": "Static dependency and byte-equality checks; runtime map loading is separate"}
    (output / "custom-maps.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")
    print("CUSTOM_MAP_CONTENT_PASS: " + ", ".join(item["name"] for item in maps), flush=True)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-zip", required=True)
    parser.add_argument("--custom", required=True, help="Custom cstrike asset directory")
    parser.add_argument("--output", required=True, help="Empty build output directory")
    args = parser.parse_args()
    package(args.base_zip, args.custom, args.output)
