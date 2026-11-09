"""检查 skin/models/ 里的 glb 符合页面的约定：大小、面数、动画和形态键。"""
import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESIDENTS = ("ac", "ag", "ayu", "ak")
CLIPS = {"idle", "walk", "sit", "sit_floor", "lie"}


def read_json(path: Path) -> dict:
    data = path.read_bytes()
    magic, version, _ = struct.unpack("<III", data[:12])
    assert magic == 0x46546C67 and version == 2
    length, kind = struct.unpack("<II", data[12:20])
    assert kind == 0x4E4F534A
    return json.loads(data[20:20 + length])


class ModelFiles(unittest.TestCase):
    def test_models(self):
        for rid in RESIDENTS:
            with self.subTest(rid):
                path = ROOT / "skin" / "models" / f"{rid}.glb"
                self.assertTrue(path.exists())
                self.assertLessEqual(path.stat().st_size, 3 * 1024 * 1024)
                gltf = read_json(path)
                tris = sum(gltf["accessors"][p["indices"]]["count"] // 3 for m in gltf["meshes"] for p in m["primitives"])
                self.assertLessEqual(tris, 15000)
                self.assertTrue(gltf.get("skins"))
                self.assertEqual({a["name"] for a in gltf["animations"]}, CLIPS)
                names = [n for m in gltf["meshes"] for n in (m.get("extras") or {}).get("targetNames", [])]
                self.assertIn("eyes_closed", names)

    def test_example_config_points_at_models(self):
        import yaml
        cfg = yaml.safe_load((ROOT / "home.example.yaml").read_text(encoding="utf-8"))
        for r in cfg["residents"]:
            self.assertEqual(r.get("model"), f"models/{r['id']}.glb")


if __name__ == "__main__":
    unittest.main()
