"""Targeted repair for the pinned engine's shared fragment-buffer ownership."""
import hashlib
from pathlib import Path
import sys

ENGINE_COMMIT = "d3bc7fabeea8586f38a501b4cc6233fa0545f5f0"
SOURCE_SHA256 = "59c8036661a9cd2c640b820a5b3e4ed0f1ef726d2f2db024e1a185d5fd7121b7"
PATCH_ID = "FX_CS16_NET_SENDLONG_FREE_V1"
BAD_CLEANUP = """    if (fragments && fragments[0] != buf) {
        for (int i = 0; i < packet_count; ++i)
            free(fragments[i]);
    }
"""


def repaired_source(original):
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("Pinned engine net_ws.c checksum mismatch; repair stopped")
    source = original.decode("utf-8")
    declaration = "int packet_count = 1, sequence_number = 0, total_size = 0, ret = 0;"
    if source.count(BAD_CLEANUP) != 1 or source.count(declaration) != 1:
        raise ValueError("Pinned engine repair anchors differ; repair stopped")
    source = source.replace(declaration, declaration.replace("ret = 0", "ret = -1"), 1)
    source = source.replace(BAD_CLEANUP, """    /* FX_CS16: fragment pointers borrow slices of fragment_data_block.
     * Only that owning allocation is freed above. The unsplit packet borrows
     * the caller's buffer. Neither path owns an individual fragments[i]. */
""", 1)
    return source.encode("utf-8")


if __name__ == "__main__":
    target = Path(sys.argv[1])
    result = repaired_source(target.read_bytes())
    target.write_bytes(result)
    print(PATCH_ID + " applied; patched net_ws.c sha256=" + hashlib.sha256(result).hexdigest())
