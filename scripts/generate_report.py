#!/usr/bin/env python3
import argparse
import asyncio
import json
import struct
import sys
from pathlib import Path

SOCKET_PATH = "/run/user/1000/notebooklm-mcp/broker.sock"
NOTEBOOK_ID = "b61be5ed-8360-42cb-bdd6-328160a0eb0f"
SESSION_TOKEN = "9652d5a3c353c137ac8f7e97af531e080fb474cdd2a7f1c10ebe48be0d594cd6"

async def query_and_save(prompt: str, output_path: Path, request_key: str, title: str) -> None:
    print(f"[*] Querying notebook for: {title} (request_key: {request_key})...")
    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
    
    req = json.dumps({
        "type": "command",
        "command": "query_notebook",
        "session_token": SESSION_TOKEN,
        "notebook_id": NOTEBOOK_ID,
        "question": prompt,
        "request_key": request_key,
        "timeout_seconds": 600
    }).encode("utf-8")
    
    writer.write(struct.pack(">I", len(req)) + req)
    await writer.drain()
    
    len_bytes = await reader.readexactly(4)
    (mlen,) = struct.unpack(">I", len_bytes)
    res = json.loads((await reader.readexactly(mlen)).decode("utf-8"))
    writer.close()
    await writer.wait_closed()
    
    if not res.get("ok"):
        print(f"[!] Error returned by broker: {res.get('error')}", file=sys.stderr)
        sys.exit(1)
        
    answer = res.get("answer", "")
    citations = res.get("citations", [])
    print(f"[+] Received response ({len(answer)} chars, {len(citations)} citations).")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# Google Notebook MCP — {title}\n\n")
        f.write(answer)
        f.write("\n\n---\n## Verified Grounded Citations\n\n")
        f.write(f"Total verified citations: {len(citations)}\n\n")
        for idx, cit in enumerate(citations[:50], start=1):
            f.write(f"- [{idx}] Source ID: `{cit.get('source_id')}` (Chars: {cit.get('start_char')}-{cit.get('end_char')})\n")
    print(f"[+] Successfully wrote {output_path} ({output_path.stat().st_size} bytes)")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--key", required=True)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    
    asyncio.run(query_and_save(args.prompt, args.output, args.key, args.title))

if __name__ == "__main__":
    main()
