from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_release


class RuntimeContentsTests(unittest.TestCase):
    def test_retains_asset_and_python_runtime_dependencies(self):
        for name in ("python.exe", "pythonw.exe", "python313.zip", "python313.dll", "Lib/PIL/Image.py",
                     "Lib/PIL/_imaging.cp313-win_amd64.pyd", "Lib/tpk_ar/blob.py", "Lib/lz4/block/_block.pyd",
                     "Lib/UnityPy/resources/lzma.tpk", "Lib/UnityPy/files/SerializedFile.py",
                     "Lib/attrs-26.1.0.dist-info/METADATA", "Lib/pillow-13.0.0.dist-info/licenses/LICENSE",
                     "Lib/fmod_toolkit-0.1.3.dist-info/LICENSE", "Lib/fsspec/implementations/local.py", "LICENSE.txt"):
            self.assertTrue(package_release.runtime_file(Path(name)), name)

    def test_excludes_offline_codecs_exporters_and_native_build_artifacts(self):
        for name in ("sqlite3.dll", "_sqlite3.pyd", "Lib/PIL/_avif.cp313-win_amd64.pyd",
                     "Lib/PIL/_imagingft.cp313-win_amd64.pyd", "Lib/PIL/AvifImagePlugin.py",
                     "Lib/fmod_toolkit/libfmod/Windows/x64/fmod.dll", "Lib/astc_encoder/_encoder_none.iobj",
                     "Lib/etcpak/_etcpak_sse41.cp37-win_amd64.ipdb", "Lib/texture2ddecoder/_texture2ddecoder.pyd",
                     "Lib/UnityPy/tools/TpkClassGenerator.py", "Lib/UnityPy/export/SpriteHelper.py"):
            self.assertFalse(package_release.runtime_file(Path(name)), name)
