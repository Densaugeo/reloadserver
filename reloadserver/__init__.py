import http.server, http, pathlib, sys, argparse, ssl, builtins, contextlib, \
    threading, os
from typing import BinaryIO

# Does not seem to do be used, but leaving this import out causes uploadserver
# to not receive IPv4 requests when started with default options under Windows
import socket 

import watchdog.observers, watchdog.events

SCRIPT_TAG = b'''
<!-- Injected by reloadserver -->
<script type="text/javascript">
async function poll() {
  try {
    var res = await fetch('/api-reloadserver/wait-for-reload', { cache:
        'reload' })
    
    if(res.status == 204) {
      // Firefox-only: true forces full reload, like ctrl+F5
      location.reload(true)
    } else throw Error(`Expected 204 but got ${res.status}`)
  } catch(e) {
    console.log(`Error polling /api-reloadserver/wait-for-reload: ${e}`)
    setTimeout(poll, 1000)
  }
}
poll()
</script>
'''

reload_signal = threading.Condition()
debounce_timer = None

def reload():
    global debounce_timer
    if debounce_timer is not None:
        debounce_timer.cancel()

    with reload_signal:
        reload_signal.notify_all()

def set_reload_timer():
    global debounce_timer
    if debounce_timer is not None:
        debounce_timer.cancel()
    
    debounce_timer = threading.Timer(args.debounce_interval / 1000, reload)
    debounce_timer.start()

class WatchdogHandler(watchdog.events.PatternMatchingEventHandler):
    def on_modified(self, event) -> None: set_reload_timer()
    def on_created (self, event) -> None: set_reload_timer()
    def on_deleted (self, event) -> None: set_reload_timer()
    def on_moved   (self, event) -> None: set_reload_timer()

class SimpleHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    # To be used only on .html files, to inject the script tag
    def copyfile_interceptor(self, source: BinaryIO, outputfile: BinaryIO
        ) -> None:
        before_inject = source.read()
        if b'</html>' not in before_inject:
            print('WARNING: No closing </html> tag, reload script will be '
                'injected at end of file')
            outputfile.write(before_inject + SCRIPT_TAG)
        else:
            outputfile.write(before_inject.replace(
                b'</html>', SCRIPT_TAG + b'</html>'))

    
    def flush_headers(self) -> None:
        update_content_length = False
        
        if hasattr(self, '_headers_buffer'):
            for header in self._headers_buffer:
                if header[:13] == b'Content-type:' and b'text/html' in header:
                    setattr(self, 'copyfile', self.copyfile_interceptor)
                    update_content_length = True
        
        # If sending .html files, the Content-Length header must be updated
        # because the injected script tag alters the content's length
        if update_content_length:
            for i, header in enumerate(self._headers_buffer):
                if header[:15] == b'Content-Length:':
                    length = int(header[15:]) + len(SCRIPT_TAG)
                    
                    # Use same encoding that self.send_header() uses
                    self._headers_buffer[i] = 'Content-Length: {}\r\n'.format(
                        length).encode('latin-1', 'strict')
        
        super().flush_headers()
    
    def do_GET(self) -> None:
        if self.path == '/api-reloadserver/wait-for-reload':
            with reload_signal: reload_signal.wait()

            self.send_response(http.HTTPStatus.NO_CONTENT)
            self.end_headers()
        elif self.path == '/api-reloadserver/trigger-reload':
            self.send_response(http.HTTPStatus.METHOD_NOT_ALLOWED)
            self.end_headers()
        else:
            super().do_GET()
    
    def do_POST(self) -> None:
        if self.path == '/api-reloadserver/trigger-reload':
            reload()

            self.send_response(http.HTTPStatus.NO_CONTENT)
            self.end_headers()
        elif self.path == '/api-reloadserver/wait-for-reload':
            self.send_response(http.HTTPStatus.METHOD_NOT_ALLOWED)
            self.end_headers()
        else:
            self.send_error(http.HTTPStatus.NOT_FOUND, 'Can only POST to /api-'
                'reloadserver/trigger-reload')

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
    parser.add_argument('--watch', '-w', metavar='PATTERN', nargs='*',
        default=['*'],
        help='File(s) to watch. Accepts multiple values [default: .]')
    parser.add_argument('--ignore', '-i', metavar='PATTERN', nargs='*',
        default=[],
        help='File(s) to ignore. Accepts multiple values [default: none]')
    parser.add_argument('--skip-built-in-ignores', action='store_true', 
        default=False,
        help='Do not use the built-in ignores (dotfiles and some commonly '
        'ignored folders) (built-in ignores are never used on Windows) '
        '[default: false]')
    parser.add_argument('--blind', action='store_true', default=False,
        help='Disable file watching and trigger reloads only by HTTP request. '
        'Overrides --watch and --ignore [default: false]')
    parser.add_argument('--debounce-interval', '-D', type=int, default=500,
        help='Minimum time in ms between reloads [default: 500, minimum: 10]')
    args = parser.parse_args()

    if args.debounce_interval < 10:
        print('ERROR: Debouncing interval must be at least 10 ms (-D, '
            '--debounce-interval)')
        exit(1)
    
    ignore_patterns = args.ignore
    # Watchdog's ignore patterns are bizarre, undocumented, and on Windows
    # trying to ignore dotfiles causes all events to be ignored
    if not args.skip_built_in_ignores and os.name != 'nt':
        ignore_patterns += ['.*', '__pycache__/*', 'node_modules/*']
    
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
    
    print('Modify a watched file or POST to /api-reloadserver/trigger-reload '
        'to reload clients')
    if args.certificate: intercept_first_print()
    
    http.server.test(
        HandlerClass=SimpleHTTPRequestHandler,
        ServerClass=DualStackServer,
        port=args.port,
        bind=args.bind,
    )
