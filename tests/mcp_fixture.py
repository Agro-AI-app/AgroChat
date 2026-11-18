"""A read-only MCP server for the optional live tool-call smoke check."""

import uvicorn
from mcp.server.mcpserver import MCPServer

server = MCPServer('AgroChat smoke')


@server.tool()
def irrigation_status() -> str:
    """Return the irrigation status for the synthetic test farm."""
    return 'MCP-IRRIGATION-512'


if __name__ == '__main__':
    uvicorn.run(server.streamable_http_app(stateless_http=True, json_response=True), host='127.0.0.1', port=8092)
