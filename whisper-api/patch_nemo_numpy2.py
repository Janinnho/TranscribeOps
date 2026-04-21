"""
Post-install patch for NeMo 2.0.0 + NumPy 2.x compatibility.

NumPy 2.0 removed `np.sctypes`, but nemo 2.0.0's
preprocessing/segment.py still references it. We patch the file in
place after `pip install` so the container can run audio preprocessing.

Idempotent: running twice does nothing.
"""
import pathlib
import sys

TARGET = pathlib.Path(
    "/usr/local/lib/python3.12/site-packages/"
    "nemo/collections/asr/parts/preprocessing/segment.py"
)

REPLACEMENTS = {
    "np.sctypes['int']":   "[np.int8, np.int16, np.int32, np.int64]",
    'np.sctypes["int"]':   "[np.int8, np.int16, np.int32, np.int64]",
    "np.sctypes['uint']":  "[np.uint8, np.uint16, np.uint32, np.uint64]",
    'np.sctypes["uint"]':  "[np.uint8, np.uint16, np.uint32, np.uint64]",
    "np.sctypes['float']": "[np.float16, np.float32, np.float64]",
    'np.sctypes["float"]': "[np.float16, np.float32, np.float64]",
}


def main() -> int:
    if not TARGET.exists():
        print(f"Target not found, skipping: {TARGET}", file=sys.stderr)
        return 0
    src = TARGET.read_text()
    new = src
    for old, replacement in REPLACEMENTS.items():
        new = new.replace(old, replacement)
    if new != src:
        TARGET.write_text(new)
        print(f"Patched {TARGET} for NumPy 2.0 compatibility")
    else:
        print(f"No patch needed in {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
