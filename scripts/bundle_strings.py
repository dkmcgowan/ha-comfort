"""Pull readable strings out of the Comfort app's React Native bundle.

The Android app is React Native, and everything interesting lives in
`assets/index.android.bundle`, which is Hermes bytecode rather than
JavaScript. Full decompilation is not needed: Hermes keeps its string table
in the clear, so every API path, field name and enum value the app knows
about is sitting in that file as plain ASCII.

Usage:

    python scripts/bundle_strings.py <index.android.bundle> --out strings.txt
    python scripts/bundle_strings.py <index.android.bundle> --grep "zones/"

The strings arrive as a handful of enormous concatenated runs, because the
table has no separators. Searching the dump gives a hit plus whatever string
happened to be stored next to it, so read the context, and never assume a
path is real until a request against the API confirms it.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

# 0x1F1903C103BC1FC6, little endian, as it sits at the head of the file.
HERMES_MAGIC = bytes.fromhex("c61fbc03c103191f")

# Paths the app talks to. Deliberately loose, because the surrounding bytes
# run straight into the match.
ENDPOINT = re.compile(
    r"(?:https?://[a-zA-Z0-9._-]+|/?(?:accounts|sites|zones|devices|users|groups)"
    r"/[a-zA-Z0-9/_{}$.-]{2,60})"
)


def extract(data: bytes, minimum: int) -> list[str]:
    """Return every run of printable ASCII at least `minimum` characters long."""
    pattern = rb"[\x20-\x7e]{%d,}" % minimum
    return [run.decode("ascii") for run in re.findall(pattern, data)]


def main() -> int:
    """Run the extraction."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, help="write the full dump here")
    parser.add_argument("--grep", help="print endpoint-shaped matches containing this")
    parser.add_argument("--min", type=int, default=5, help="shortest run to keep")
    parser.add_argument("--context", type=int, default=0, help="characters either side")
    args = parser.parse_args()

    data = args.bundle.read_bytes()
    if not data.startswith(HERMES_MAGIC):
        print(
            f"warning: {args.bundle.name} does not start with the Hermes magic; "
            "this may be a plain JavaScript bundle or a different format",
            file=sys.stderr,
        )

    runs = extract(data, args.min)
    text = "\n".join(runs)
    print(f"{len(data):,} bytes, {len(runs):,} runs, {len(text):,} characters", file=sys.stderr)

    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}", file=sys.stderr)

    if args.grep:
        seen = set()
        for match in ENDPOINT.finditer(text):
            if args.grep not in match.group(0):
                continue
            start = max(0, match.start() - args.context)
            end = min(len(text), match.end() + args.context)
            snippet = text[start:end]
            if snippet not in seen:
                seen.add(snippet)
                print(snippet)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
