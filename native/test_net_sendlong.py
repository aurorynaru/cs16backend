"""Compile the actual pinned C function, reproduce its failure, test the repair.

The networking callback verifies split payloads without a game engine or test
double for the allocation code. AddressSanitizer checks the original/fixed
function; injected allocation failures also exercise partial cleanup.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from patch_engine import repaired_source

PREAMBLE = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
typedef enum { NS_CLIENT, NS_SERVER } netsrc_t;
#pragma pack(push, 1)
typedef struct { int net_id; int sequence_number; short packet_id; } SPLITPACKET;
#pragma pack(pop)
#define NET_HEADER_SPLITPACKET -2
#define Q_min(a,b) ((a) < (b) ? (a) : (b))
static struct { int sequence_number; } net;
static int allocation_number, fail_allocation;
static void *test_malloc(size_t size) {
  allocation_number++;
  if (fail_allocation == allocation_number) return NULL;
  return malloc(size);
}
static const unsigned char *expected;
static size_t expected_len, split_size;
static int callback_fail, callback_count;
static int capture(netsrc_t sock, char **packets, size_t *sizes, int count,
                   int sequence, const struct sockaddr_storage *to, size_t tolen) {
  (void)sock; (void)to; (void)tolen;
  callback_count++;
  if (callback_fail) return -1;
  size_t offset = 0;
  for (int i = 0; i < count; ++i) {
    const unsigned char *data = (const unsigned char *)packets[i];
    size_t size = sizes[i];
    if (expected_len > split_size) {
      assert(size > sizeof(SPLITPACKET));
      SPLITPACKET hdr;
      memcpy(&hdr, data, sizeof(hdr));
      assert(hdr.net_id == NET_HEADER_SPLITPACKET);
      assert(hdr.sequence_number == sequence);
      assert((uint16_t)hdr.packet_id == (uint16_t)((i << 8) + count));
      data += sizeof(hdr); size -= sizeof(hdr);
    }
    assert(offset + size <= expected_len);
    assert(memcmp(data, expected + offset, size) == 0);
    offset += size;
  }
  assert(offset == expected_len);
  return (int)offset;
}
static int (*g_sendto)(netsrc_t, char **, size_t *, int, int,
                     const struct sockaddr_storage *, size_t) = capture;
#define malloc test_malloc
"""

TESTS = r"""
#undef malloc
static void check(size_t length, size_t split, int fail_n, int send_error) {
  unsigned char payload[65535];
  for (size_t i = 0; i < sizeof(payload); ++i) payload[i] = (unsigned char)(i * 37);
  struct sockaddr_storage target = {0};
  expected = payload; expected_len = length; split_size = split;
  allocation_number = callback_count = 0;
  fail_allocation = fail_n; callback_fail = send_error;
  int result = NET_SendLong(NS_SERVER, 1, (const char *)payload, length, 0,
                            &target, sizeof(target), split);
  if (fail_n) { assert(result == -1); assert(callback_count == 0); }
  else if (send_error) { assert(result == -1); assert(callback_count == 1); }
  else { assert(result == (int)length); assert(callback_count == 1); }
  for (size_t i = 0; i < sizeof(payload); ++i) assert(payload[i] == (unsigned char)(i * 37));
}
int main(void) {
  check(32, 1400, 0, 0);     /* borrowed caller buffer must survive */
  check(1400, 1400, 0, 0);   /* exact unsplit boundary */
  check(1401, 1400, 0, 0);   /* first split boundary: old code double-frees */
  check(8192, 508, 0, 0);
  check(65535, 1400, 0, 0);
  check(32, 1400, 0, 1);
  check(8192, 508, 0, 1);    /* transport failure must still clean up once */
  for (int n = 1; n <= 3; ++n) check(8192, 508, n, 0);
  for (int n = 1; n <= 2; ++n) check(32, 1400, n, 0);
  for (int n = 0; n < 2000; ++n) check(8192, 508, 0, 0);
  puts("PASS_NET_SENDLONG_OWNERSHIP: 2012 payload/cleanup cases; caller bytes intact");
  return 0;
}
"""


def function(source):
    start = source.index("static int NET_SendLong(")
    end = source.index("\n/*", start)
    return source[start:end]


def main():
    original = Path(sys.argv[1]).read_bytes()
    fixed = repaired_source(original)
    env = os.environ.copy()
    env["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
    with tempfile.TemporaryDirectory(prefix="FX_CS16_netfree-") as directory:
        for label, source in (("original", original), ("fixed", fixed)):
            code = Path(directory) / (label + ".c")
            program = Path(directory) / label
            code.write_text(PREAMBLE + function(source.decode("utf8")) + TESTS)
            subprocess.run(["gcc", "-g", "-O1", "-fno-omit-frame-pointer", "-fsanitize=address",
                            str(code), "-o", str(program)], check=True)
            result = subprocess.run([str(program)], env=env, capture_output=True, text=True)
            if label == "original":
                if result.returncode == 0 or "attempting double-free" not in result.stderr:
                    raise SystemExit("Original pinned function did not reproduce the expected double-free:\n" + result.stderr[:2000])
                print("REPRODUCED_ORIGINAL_NET_SENDLONG_DOUBLE_FREE", flush=True)
                lines = result.stderr.splitlines()
                print("\n".join(lines[:16]), flush=True)
            else:
                if result.returncode != 0:
                    raise SystemExit("Repaired function failed:\n" + result.stderr[:4000])
                print(result.stdout.strip(), flush=True)
                print("PASS_ADDRESS_SANITIZER_AND_ALLOCATION_FAILURE_CLEANUP", flush=True)


if __name__ == "__main__":
    main()
