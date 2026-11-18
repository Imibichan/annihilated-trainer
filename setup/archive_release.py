"""Write the flat release ZIP and verify its contents against the file manifest."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def archive(folder, output):
    folder = folder.resolve(strict=True)
    output = output.resolve()
    if output.is_relative_to(folder):
        raise ValueError("Place the ZIP outside the staging folder.")
    sums = folder / "SHA256SUMS.txt"
    files = sorted(
        (p for p in folder.rglob("*") if p.is_file() and p != sums
         and "__pycache__" not in p.parts and p.suffix != ".pyc"),
        key=lambda p: p.relative_to(folder).as_posix().casefold(),
    )
    expected = {p.relative_to(folder).as_posix(): digest(p) for p in files}
    sums.write_text("".join(f"{value}  {name}\n" for name, value in expected.items()),
                    encoding="utf-8", newline="\r\n")
    expected[sums.name] = digest(sums)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        temp = Path(handle.name)
    try:
        with ZipFile(temp, "w", ZIP_DEFLATED, compresslevel=6) as packed:
            for name in expected:
                packed.write(folder / name, name)
        with ZipFile(temp) as packed:
            if packed.namelist() != list(expected):
                raise ValueError("The archived file list differs from the manifest.")
            for name, value in expected.items():
                with packed.open(name) as member:
                    if hashlib.file_digest(member, "sha256").hexdigest() != value:
                        raise ValueError(f"File verification failed: {name}")
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    print(f"{len(expected)} files, {output.stat().st_size} bytes, SHA-256 {digest(output)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    archive(args.folder, args.output)
