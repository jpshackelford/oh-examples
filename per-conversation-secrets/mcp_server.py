#!/usr/bin/env python3
"""
Simple MCP Server that validates a secret token.

This server exposes a single tool `validate_token` that checks if the
Authorization header contains the expected secret token.

Usage:
    python mcp_server.py --port 12000 --expected-token "my-secret-token"

The server validates tokens passed via:
1. Authorization: Bearer {token} header
2. X-Secret-Token header
"""

import argparse
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global config set by command line args
EXPECTED_TOKEN: str = ""
VALIDATED_COUNT: int = 0


class MCPHandler(BaseHTTPRequestHandler):
    """HTTP handler for MCP protocol requests."""

    def log_message(self, format: str, *args: Any) -> None:
        """Override to use our logger."""
        logger.info(f"{self.address_string()} - {format % args}")

    def _send_json_response(self, data: dict, status: int = 200) -> None:
        """Send a JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _get_token_from_headers(self) -> str | None:
        """Extract token from various header formats."""
        # Try Authorization: Bearer {token}
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]
        
        # Try X-Secret-Token header
        secret_header = self.headers.get('X-Secret-Token')
        if secret_header:
            return secret_header
        
        return None

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == '/health' or self.path == '/':
            self._send_json_response({
                'status': 'ok',
                'server': 'token-validator-mcp',
                'validated_count': VALIDATED_COUNT
            })
        else:
            self._send_json_response({'error': 'Not found'}, 404)

    def do_POST(self) -> None:
        """Handle POST requests (MCP protocol)."""
        global VALIDATED_COUNT
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else '{}'
        
        try:
            request = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json_response({'error': 'Invalid JSON'}, 400)
            return

        # Log the request for debugging
        logger.info(f"Request path: {self.path}")
        logger.info(f"Headers: {dict(self.headers)}")
        logger.info(f"Body: {body[:500]}")

        # Handle MCP initialization
        if self.path == '/mcp' or self.path == '/':
            method = request.get('method', '')
            
            if method == 'initialize':
                self._send_json_response({
                    'jsonrpc': '2.0',
                    'id': request.get('id'),
                    'result': {
                        'protocolVersion': '2024-11-05',
                        'capabilities': {'tools': {}},
                        'serverInfo': {
                            'name': 'token-validator',
                            'version': '1.0.0'
                        }
                    }
                })
            
            elif method == 'notifications/initialized':
                # No response needed for notifications
                self._send_json_response({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {}})
            
            elif method == 'tools/list':
                self._send_json_response({
                    'jsonrpc': '2.0',
                    'id': request.get('id'),
                    'result': {
                        'tools': [{
                            'name': 'validate_token',
                            'description': 'Validates that the secret token was correctly passed to this MCP server',
                            'inputSchema': {
                                'type': 'object',
                                'properties': {
                                    'echo_message': {
                                        'type': 'string',
                                        'description': 'Optional message to echo back on success'
                                    }
                                },
                                'required': []
                            }
                        }]
                    }
                })
            
            elif method == 'tools/call':
                tool_name = request.get('params', {}).get('name', '')
                arguments = request.get('params', {}).get('arguments', {})
                
                if tool_name == 'validate_token':
                    token = self._get_token_from_headers()
                    echo_msg = arguments.get('echo_message', '')
                    
                    logger.info(f"Validating token: '{token}' vs expected: '{EXPECTED_TOKEN}'")
                    
                    if token == EXPECTED_TOKEN:
                        VALIDATED_COUNT += 1
                        result_text = f"✅ SUCCESS! Token validated correctly. Validation count: {VALIDATED_COUNT}"
                        if echo_msg:
                            result_text += f"\nEcho: {echo_msg}"
                        
                        self._send_json_response({
                            'jsonrpc': '2.0',
                            'id': request.get('id'),
                            'result': {
                                'content': [{
                                    'type': 'text',
                                    'text': result_text
                                }]
                            }
                        })
                    else:
                        self._send_json_response({
                            'jsonrpc': '2.0',
                            'id': request.get('id'),
                            'result': {
                                'content': [{
                                    'type': 'text',
                                    'text': f"❌ FAILED! Token mismatch.\nReceived: '{token}'\nExpected: '{EXPECTED_TOKEN}'"
                                }],
                                'isError': True
                            }
                        })
                else:
                    self._send_json_response({
                        'jsonrpc': '2.0',
                        'id': request.get('id'),
                        'error': {'code': -32601, 'message': f'Unknown tool: {tool_name}'}
                    })
            
            else:
                self._send_json_response({
                    'jsonrpc': '2.0',
                    'id': request.get('id'),
                    'error': {'code': -32601, 'message': f'Unknown method: {method}'}
                })
        else:
            self._send_json_response({'error': 'Not found'}, 404)


def main() -> None:
    global EXPECTED_TOKEN
    
    parser = argparse.ArgumentParser(description='MCP Token Validator Server')
    parser.add_argument('--port', type=int, default=12000, help='Port to listen on')
    parser.add_argument('--expected-token', type=str, required=True, help='Expected token value')
    args = parser.parse_args()
    
    EXPECTED_TOKEN = args.expected_token
    
    server = HTTPServer(('0.0.0.0', args.port), MCPHandler)
    logger.info(f"Starting MCP Token Validator on port {args.port}")
    logger.info(f"Expected token: {EXPECTED_TOKEN}")
    logger.info(f"Endpoints:")
    logger.info(f"  GET  /health - Health check")
    logger.info(f"  POST /mcp    - MCP protocol endpoint")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()
