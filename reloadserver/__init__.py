import http.server, http, pathlib, sys, argparse, ssl, builtins, contextlib, threading
from typing import BinaryIO

# Does not seem to do be used, but leaving this import out causes uploadserver to not
# receive IPv4 requests when started with default options under Windows
import socket 

import watchdog.observers, watchdog.events

SCRIPT_TAG = b'''
<!-- Injected by reloadserver -->
<script type="text/javascript">
async function poll() {
  try {
    var res = await fetch('/api-reloadserver/wait-for-reload', { cache: 'reload'})
    
    if(res.status == 204) {
      // Firefox-only: true forces full reload, like ctrl+F5
      location.reload(true)
    } else throw Error(`Expected 204 but got $(res.status)`)
  } catch(e) {
    console.log(`Error polling /api-reloadserver/wait-for-reload: ${e}`)
    setTimeout(poll, 1000)
  }
}
setTimeout(poll, 1000)
</script>
'''

reload_signal = threading.Condition()

class WatchdogHandler(watchdog.events.PatternMatchingEventHandler):
    def on_modified(self, event) -> None:
        with reload_signal: reload_signal.notify_all()

class SimpleHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    # Need this to intercept the Content-Length header when sending .html files, because
    # the injected script tag alters the content's length
    def send_header_interceptor(self, keyword: str, value: str) -> None:
        if keyword == 'Content-Length': value = str(int(value) + len(SCRIPT_TAG))
        super().send_header(keyword, value)
    
    # To be used only on .html files, to inject the script tag
    def copyfile_interceptor(self, source: BinaryIO, outputfile: BinaryIO) -> None:
        outputfile.write(source.read().replace(b'</html>', SCRIPT_TAG + b'</html>'))
    
    def do_GET(self) -> None:
        if self.path == '/api-reloadserver/wait-for-reload':
            with reload_signal: reload_signal.wait()
            
            self.send_response(http.HTTPStatus.NO_CONTENT)
            self.end_headers()
        elif self.path == '/api-reloadserver/trigger-reload':
            self.send_response(http.HTTPStatus.METHOD_NOT_ALLOWED)
            self.end_headers()
        else:
            if self.path[-5:] == '.html':
                # These don't need to be removed afterward, because each .do_GET() happens
                # in its own thread and they don't share
                setattr(self, 'send_header', self.send_header_interceptor)
                setattr(self, 'copyfile', self.copyfile_interceptor)
            
            super().do_GET()
    
    def do_POST(self) -> None:
        if self.path == '/api-reloadserver/trigger-reload':
            with reload_signal: reload_signal.notify_all()
            
            self.send_response(http.HTTPStatus.NO_CONTENT)
            self.end_headers()
        elif self.path == '/api-reloadserver/wait-for-reload':
            self.send_response(http.HTTPStatus.METHOD_NOT_ALLOWED)
            self.end_headers()
        else:
            self.send_error(http.HTTPStatus.NOT_FOUND, 'Can only POST to /api-reloadserver/trigger-reload')

def intercept_first_print() -> None:
    # Use the right protocol in the first print call in case of HTTPS
    old_print = builtins.print
    def new_print(*args, **kwargs):
        old_print(args[0].replace('HTTP', 'HTTPS').replace('http', 'https'), **kwargs)
        builtins.print = old_print
    builtins.print = new_print

def ssl_wrap(socket) -> None:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    
    # Server certificate handling
    certificate = pathlib.Path(args.certificate).resolve()
    
    if not certificate.is_file():
        print('Server certificate "{}" not found, exiting'.format(certificate))
        sys.exit(4)
    
    context.load_cert_chain(certfile=certificate)
    
    try:
        return context.wrap_socket(socket, server_side=True)
    except ssl.SSLError as e:
        print('SSL error: "{}", exiting'.format(e))
        sys.exit(5)

def main() -> None:
    global args
    
    parser = argparse.ArgumentParser()
    parser.add_argument('port', type=int, default=8000, nargs='?',
        help='Specify alternate port [default: 8000]')
    parser.add_argument('--bind', '-b', metavar='ADDRESS',
        help='Specify alternate bind address [default: all interfaces]')
    parser.add_argument('--certificate', '-c',
        help='Specify HTTPS server certificate to use [default: none]')
    parser.add_argument('--watch', '-w', metavar='PATTERN', nargs='*', default=['*'],
        help='File(s) to watch. Accepts multiple values [default: .]')
    parser.add_argument('--ignore', '-i', metavar='PATTERN', nargs='*', default=[],
        help='File(s) to ignore. Accepts multiple values [default: none')
    parser.add_argument('--skip-built-in-ignores', action='store_true', default=False,
        help='Do not use the built-in ignores (dotfiles and some commonly ignored folders')
    parser.add_argument('--blind', action='store_true', default=False,
        help='Disable file watching and trigger reloads only by HTTP request. Overrides --watch and --ignore [default: false]')
    args = parser.parse_args()
    
    ignore_patterns = [] if args.skip_built_in_ignores else [
        '.*', '__pycache__/*', 'node_modules/*'
    ] + args.ignore
    
    if not args.blind:
        observer = watchdog.observers.Observer()
        observer.schedule(WatchdogHandler(
            patterns=args.watch,
            ignore_patterns=ignore_patterns,
            ignore_directories=True,
            case_sensitive=True,
        ), path='.', recursive=True)
        observer.start()
    
    class DualStackServer(http.server.ThreadingHTTPServer):
        def server_bind(self):
            # suppress exception when protocol is IPv4
            with contextlib.suppress(Exception):
                self.socket.setsockopt(
                    socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            bind = super().server_bind()
            if args.certificate:
                self.socket = ssl_wrap(self.socket)
            return bind
    
    print('Modify a watched file or POST to /api-reloadserver/trigger-reload to reload clients')
    if args.certificate: intercept_first_print()
    
    http.server.test(
        HandlerClass=SimpleHTTPRequestHandler,
        ServerClass=DualStackServer,
        port=args.port,
        bind=args.bind,
    )
