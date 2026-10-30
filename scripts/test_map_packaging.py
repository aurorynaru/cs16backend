import contextlib
import hashlib
import io
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import zipfile
from package_maps import collect_assets, inspect_bsp, package

CUSTOM = Path(__file__).resolve().parents[1] / "custom-maps" / "cstrike"


class MapPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="FX_CS16_maps_test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.custom = self.root / "custom"
        shutil.copytree(CUSTOM, self.custom)
        self.output = self.root / "output"
        self.base = self.root / "base.zip"
        self.bsp = (self.custom / "maps/cs_deathmatch.bsp").read_bytes()
        names = inspect_bsp(self.bsp)["externalTextures"]
        # Explicit synthetic WAD directory; actual stock WADs are checked separately.
        wad = b"WAD3" + struct.pack("<ii", len(names), 12)
        for name in names:
            wad += struct.pack("<iiiBBH16s", 0, 0, 0, 0x43, 0, 0, name.encode("latin1"))
        with zipfile.ZipFile(self.base, "w") as base:
            base.writestr("valve/halflife.wad", wad)
            base.writestr("cstrike/stock.txt", b"stock content preserved")

    def run_package(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return package(self.base, self.custom, self.output)

    def test_actual_supplied_map_and_nav_are_identical_on_server_and_client(self):
        original = self.base.read_bytes()
        manifest = self.run_package()
        self.assertEqual(self.base.read_bytes(), original)
        self.assertEqual([item["name"] for item in manifest["maps"]], ["cs_deathmatch"])
        with zipfile.ZipFile(self.output / "gamefiles.zip") as client:
            self.assertEqual(client.read("cstrike/stock.txt"), b"stock content preserved")
            for record in manifest["files"]:
                source = CUSTOM / Path(record["path"]).relative_to("cstrike")
                server = self.output / "server" / record["path"]
                self.assertEqual(client.read(record["path"]), source.read_bytes())
                self.assertEqual(server.read_bytes(), source.read_bytes())
                self.assertEqual(hashlib.sha256(server.read_bytes()).hexdigest(), record["sha256"])
        self.assertEqual((self.output / "gamefiles.sha256").read_text().strip(), manifest["gamefilesSHA256"])

    def test_source_map_rejected_before_output(self):
        (self.custom / "maps/wrong.bsp").write_bytes(b"VBSP" + struct.pack("<i", 20) + bytes(124))
        with self.assertRaisesRegex(ValueError, "Source BSP"):
            self.run_package()
        self.assertFalse(self.output.exists())

    def test_corrupt_lump_and_missing_texture_rejected(self):
        bad = bytearray(self.bsp)
        struct.pack_into("<ii", bad, 4, len(bad) + 1, 100)
        with self.assertRaisesRegex(ValueError, "lump"):
            inspect_bsp(bad)
        with zipfile.ZipFile(self.base, "w") as base:
            base.writestr("cstrike/stock.txt", b"no WADs")
        with self.assertRaisesRegex(ValueError, "unresolved external textures"):
            self.run_package()
        self.assertFalse(self.output.exists())

    def test_stock_overwrite_and_configuration_injection_rejected(self):
        with zipfile.ZipFile(self.base, "a") as base:
            base.writestr("cstrike/maps/cs_deathmatch.bsp", self.bsp)
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.run_package()
        (self.custom / "server.cfg").write_text("unwanted console commands")
        with self.assertRaisesRegex(ValueError, "Unsupported custom asset"):
            collect_assets(self.custom)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
