"""Generate IMA pagination cursors.

The MCP `get_knowledge_list` cursor is a base64-encoded protobuf whose field 1
is a varint item offset (verified empirically: offset 5 with limit=2 returns
items #6 and #7). Forging it lets us shard a single listing into independent
offset ranges that can be crawled in parallel.

Usage:
    python ima_cursor.py 0 50 100 150 ...
"""
import base64
import sys


def varint(n: int) -> bytes:
    """Encode a non-negative int as a protobuf varint."""
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def cursor_for(offset: int) -> str:
    """Return the base64 cursor that starts listing at `offset`."""
    return base64.b64encode(b"\x08" + varint(offset)).decode("ascii")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("usage: ima_cursor.py <offset> [offset ...]")
        sys.exit(1)
    for a in args:
        print("%-6s %s" % (a, cursor_for(int(a))))


if __name__ == "__main__":
    main()
