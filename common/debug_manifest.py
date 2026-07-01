import json
import binascii
from pathlib import Path


def dump_manifest(manifest_obj, manifest_dict=None, framed_bytes=None):
    """
    Dumps every representation of the manifest.

    1. Python object
    2. Pretty JSON
    3. Raw binary frame
    4. Hex dump
    5. Saves everything to disk
    """

    print("\n" + "=" * 80)
    print("DIODEFLOW MANIFEST DEBUG")
    print("=" * 80)

    ##################################################################
    # Python Object
    ##################################################################

    print("\n[1] PYTHON OBJECT\n")

    try:
        for k, v in vars(manifest_obj).items():
            print(f"{k:30}: {v}")
    except Exception:
        print(manifest_obj)

    ##################################################################
    # Dictionary
    ##################################################################

    if manifest_dict is None:
        try:
            manifest_dict = vars(manifest_obj)
        except Exception:
            manifest_dict = {}

    print("\n" + "=" * 80)
    print("[2] JSON MANIFEST")
    print("=" * 80)

    pretty_json = json.dumps(manifest_dict, indent=4)

    print(pretty_json)

    Path("debug").mkdir(exist_ok=True)

    with open("debug/manifest.json", "w") as f:
        f.write(pretty_json)

    ##################################################################
    # Binary
    ##################################################################

    if framed_bytes is not None:

        print("\n" + "=" * 80)
        print("[3] FRAMED BINARY")
        print("=" * 80)

        print(f"Frame Size : {len(framed_bytes)} bytes")

        with open("debug/manifest.bin", "wb") as f:
            f.write(framed_bytes)

        ##################################################################
        # Hex
        ##################################################################

        print("\n" + "=" * 80)
        print("[4] HEX DUMP")
        print("=" * 80)

        hex_dump = binascii.hexlify(framed_bytes).decode()

        for i in range(0, len(hex_dump), 64):
            print(hex_dump[i:i + 64])

        with open("debug/manifest.hex", "w") as f:
            f.write(hex_dump)

        ##################################################################
        # Decode Frame
        ##################################################################

        print("\n" + "=" * 80)
        print("[5] FRAME HEADER")
        print("=" * 80)

        version = framed_bytes[0]

        length = int.from_bytes(
            framed_bytes[1:5],
            "big"
        )

        crc = framed_bytes[-4:]

        print(f"Version        : {version}")
        print(f"Payload Length : {length}")
        print(f"CRC32C         : {crc.hex()}")

    print("\n" + "=" * 80)
    print("Manifest dumped into ./debug/")
    print("=" * 80)