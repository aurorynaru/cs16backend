# Pinned native build inputs

The native server files under `server/`, plus `go.mod`/`go.sum`, are copied from
balintsoos/cs16-web-server commit
`b32833844149f00c94f040be17d40e2ba0e99c2b`. Its MIT notice is included at
`../UPSTREAM-LICENSE.txt`. These source files are not modified by this repair.

Engine: https://github.com/jklenner/xash3d-fwgs/tree/d3bc7fabeea8586f38a501b4cc6233fa0545f5f0

CGO wrapper: https://github.com/jklenner/goxash3d-fwgs/tree/90b4aa816099db3c45cfa01dd8246f12473bce22

These surviving repositories contain the previously referenced yohimik engine
and wrapper commits. The engine is GPL-3.0-or-later as stated in its source
headers. Its source and license notices remain in the build stage. The source
patch is fully expressed in `patch_engine.py`; it accepts only the exact pinned
net_ws.c SHA-256 and fails closed if its input differs. This package contains
no compiled engine or game assets.

The source regression extracts the actual original and repaired NET_SendLong
function. It checks packet reassembly, caller-buffer preservation, send errors,
partial allocation cleanup and repeated split sends under AddressSanitizer.
The surrounding C harness supplies types and a synchronous packet capture;
this is not a full engine/server/player test.

Local regression command (Linux with Python 3, GCC and AddressSanitizer):

```sh
python3 test_net_sendlong.py /path/to/pinned/engine/common/net_ws.c
```

The Dockerfile runs this check before applying the patch to the source build.
