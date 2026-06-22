"""Tiny static server for local preview of the web app (docs/)."""
import functools
import http.server
import socketserver

DOCS = "/Users/blakebrennan/Desktop/Stock-Valuator/docs"
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DOCS)
with socketserver.TCPServer(("127.0.0.1", 8123), Handler) as httpd:
    httpd.serve_forever()
