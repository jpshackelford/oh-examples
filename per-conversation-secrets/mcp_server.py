#!/usr/bin/env python3
"""
MCP Server that validates a secret token, supporting SSE transport.

This server exposes a single tool `validate_token` that checks if the
Authorization header contains the expected secret token.

Supports MCP SSE transport:
- GET /mcp - SSE event stream for server-to-client messages
- POST /mcp - JSON-RPC messages from client

Usage:
    python mcp_server.py --port 12000 --expected-token "my-secret-token"
"""

import argparse
import json
import logging
import queue
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global config
EXPECTED_TOKEN: str = ""
VALIDATED_COUNT: int = 0

# SSE clients - maps session_id to response queue
SSE_CLIENTS: dict[str, queue.Queue] = {}
SSE_LOCK = threading.Lock()


class MCPHandler(BaseHTTPRequestHandler):
    """HTTP handler for MCP protocol with SSE support."""
    
    protocol_version = 'HTTP/1.1'

    def log_message(self, format: str, *args: Any) -> None:
        """Override to use our logger."""
        logger.info(f"{self.address_string()} - {format % args}")

    def _get_token_from_headers(self) -> str | None:
        """Extract token from Authorization header."""
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]
        return None

    def _send_json_response(self, data: dict, status: int = 200) -> None:
        """Send a JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _send_sse_event(self, event_type: str, data: Any) -> str:
        """Format an SSE event."""
        if isinstance(data, dict):
            data_str = json.dumps(data)
        else:
            data_str = str(data)
        return f"event: {event_type}\ndata: {data_str}\n\n"

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self) -> None:
        """Handle GET requests - SSE endpoint or health check."""
        if self.path == '/health' or self.path == '/':
            self._send_json_response({
                'status': 'ok',
                'server': 'token-validator-mcp',
                'validated_count': VALIDATED_COUNT
            })
            return
        
        if self.path.startswith('/mcp'):
            self._handle_sse_connection()
            return
        
        self._send_json_response({'error': 'Not found'}, 404)

    def _handle_sse_connection(self) -> None:
        """Handle SSE connection for MCP."""
        session_id = str(uuid.uuid4())
        response_queue: queue.Queue = queue.Queue()
        
        with SSE_LOCK:
            SSE_CLIENTS[session_id] = response_queue
        
        logger.info(f"SSE connection opened: {session_id}")
        
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            # Send endpoint event with session ID for POST messages
            # The MCP spec says this should be just the URI string
            endpoint_event = self._send_sse_event('endpoint', f'/mcp?session={session_id}')
            self.wfile.write(endpoint_event.encode())
            self.wfile.flush()
            
            # Keep connection alive and send queued responses
            while True:
                try:
                    # Check for queued messages (with timeout for keepalive)
                    try:
                        msg = response_queue.get(timeout=15)
                        event = self._send_sse_event('message', msg)
                        self.wfile.write(event.encode())
                        self.wfile.flush()
                    except queue.Empty:
                        # Send keepalive comment
                        self.wfile.write(': keepalive\n\n'.encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
        finally:
            with SSE_LOCK:
                SSE_CLIENTS.pop(session_id, None)
            logger.info(f"SSE connection closed: {session_id}")

    def do_POST(self) -> None:
        """Handle POST requests - MCP JSON-RPC messages."""
        global VALIDATED_COUNT
        
        if not self.path.startswith('/mcp'):
            self._send_json_response({'error': 'Not found'}, 404)
            return
        
        # Extract session ID from query string
        session_id = None
        if '?' in self.path:
            query = self.path.split('?', 1)[1]
            for param in query.split('&'):
                if param.startswith('session='):
                    session_id = param.split('=', 1)[1]
                    break
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else '{}'
        
        try:
            request = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json_response({'error': 'Invalid JSON'}, 400)
            return

        logger.info(f"POST /mcp session={session_id}")
        logger.info(f"  Headers: Authorization={self.headers.get('Authorization', 'none')[:30]}...")
        logger.info(f"  Body: {body[:200]}")

        method = request.get('method', '')
        request_id = request.get('id')
        
        response = self._handle_mcp_method(method, request, request_id)
        
        # If we have a session, queue the response for SSE
        if session_id and session_id in SSE_CLIENTS:
            SSE_CLIENTS[session_id].put(response)
            # Send accepted response
            self._send_json_response({'status': 'accepted'}, 202)
        else:
            # Direct response (for non-SSE clients)
            self._send_json_response(response)

    def _handle_mcp_method(self, method: str, request: dict, request_id: Any) -> dict:
        """Handle MCP JSON-RPC method."""
        global VALIDATED_COUNT
        
        if method == 'initialize':
            return {
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'protocolVersion': '2024-11-05',
                    'capabilities': {'tools': {}},
                    'serverInfo': {
                        'name': 'token-validator',
                        'version': '1.0.0'
                    }
                }
            }
        
        elif method == 'notifications/initialized':
            return {'jsonrpc': '2.0', 'id': request_id, 'result': {}}
        
        elif method == 'tools/list':
            return {
                'jsonrpc': '2.0',
                'id': request_id,
                'result': {
                    'tools': [{
                        'name': 'validate_token',
                        'description': 'Validates that the secret token was correctly passed to this MCP server via config expansion',
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
            }
        
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
                    
                    return {
                        'jsonrpc': '2.0',
                        'id': request_id,
                        'result': {
                            'content': [{'type': 'text', 'text': result_text}]
                        }
                    }
                else:
                    return {
                        'jsonrpc': '2.0',
                        'id': request_id,
                        'result': {
                            'content': [{
                                'type': 'text',
                                'text': f"❌ FAILED! Token mismatch.\nReceived: '{token}'\nExpected: '{EXPECTED_TOKEN}'"
                            }],
                            'isError': True
                        }
                    }
            else:
                return {
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'error': {'code': -32601, 'message': f'Unknown tool: {tool_name}'}
                }
        
        else:
            return {
                'jsonrpc': '2.0',
                'id': request_id,
                'error': {'code': -32601, 'message': f'Unknown method: {method}'}
            }


class ThreadedHTTPServer(HTTPServer):
    """HTTP server that handles each request in a new thread."""
    def process_request(self, request, client_address):
        thread = threading.Thread(target=self.process_request_thread, args=(request, client_address))
        thread.daemon = True
        thread.start()
    
    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def main() -> None:
    global EXPECTED_TOKEN
    
    parser = argparse.ArgumentParser(description='MCP Token Validator Server with SSE support')
    parser.add_argument('--port', type=int, default=12000, help='Port to listen on')
    parser.add_argument('--expected-token', type=str, required=True, help='Expected token value')
    args = parser.parse_args()
    
    EXPECTED_TOKEN = args.expected_token
    
    server = ThreadedHTTPServer(('0.0.0.0', args.port), MCPHandler)
    logger.info(f"Starting MCP Token Validator (SSE) on port {args.port}")
    logger.info(f"Expected token: {EXPECTED_TOKEN}")
    logger.info(f"Endpoints:")
    logger.info(f"  GET  /health - Health check")
    logger.info(f"  GET  /mcp    - SSE event stream")
    logger.info(f"  POST /mcp    - JSON-RPC messages")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()
