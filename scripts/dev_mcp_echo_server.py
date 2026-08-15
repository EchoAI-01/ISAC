"""最小 stdio MCP echo server (R3 真机冒烟用, 非生产)。

实现 JSON-RPC 2.0 over stdio (NDJSON per line) 的最小子集, 仅响应 tools/list
与 tools/call, 供 isac MCPClient stdio 传输真机接入验证。不处理 initialize
握手 (MCPClient.connect 不发 initialize, 直接 tools/list); 收到未知 method
且带 id 时返回空 result 兜底。

用法: 在 config.jsonc 的 mcp.servers 下配置
  "echo": {"transport":"stdio","command":"<python>","args":["scripts/dev_mcp_echo_server.py"]}
Agent 级 mcp_servers:["echo"] 即可让 isac 接入本 server 的 echo 工具。
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        method = req.get("method")
        rid = req.get("id")
        if method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "echo",
                        "description": "回显输入文本 (R3 真机冒烟用)",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
            }
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}) + "\n")
            sys.stdout.flush()
        elif method == "tools/call":
            args = (req.get("params") or {}).get("arguments") or {}
            text = args.get("text", "")
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "result": {"content": [{"type": "text", "text": f"echo: {text}"}]},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
        else:
            # initialize / notifications/initialized 等未知 method: 带 id 返回空 result
            if rid is not None:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {}}) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
