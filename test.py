import pytest, os, requests, unittest, subprocess, time, urllib3, socket, threading
from pathlib import Path


assert 'VERBOSE' in os.environ, '$VERBOSE envionment variable not set'
VERBOSE = os.environ['VERBOSE']
assert VERBOSE in ['0', '1'], '$VERBOSE must be 0 or 1'
VERBOSE = int(VERBOSE)

assert 'PROTOCOL' in os.environ, '$PROTOCOL envionment variable not set'
PROTOCOL = os.environ['PROTOCOL']
assert PROTOCOL in ['HTTP', 'HTTPS'], 'Unknown $PROTOCOL: {}'.format(PROTOCOL)


wait_for_reload_responses = [None, None]
lock = threading.Lock()

server_holder = [None]


def setUpModule():
    os.mkdir(Path(__file__).parent / 'test-temp')
    os.chdir(Path(__file__).parent / 'test-temp')
    os.symlink('../reloadserver', 'reloadserver')

@pytest.fixture(autouse=True)
def setup_and_teardown():
    print()
    
    with lock:
        wait_for_reload_responses[0] = None
        wait_for_reload_responses[1] = None
    
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    yield
    
    if server_holder[0] is not None: server_holder[0].terminate()


# Verify a basic test can run. Most importantly, verify the sleep is long enough for the sever to start
def test_basic():
    spawn_server()
    
    assert get('/').status_code == 200

# Verify the --port argument is properly passed to the underlying http.server
def test_argument_passthrough():
    spawn_server(port=8080)
    
    assert get('/', port=8080).status_code == 200
    
    with pytest.raises(requests.ConnectionError): get('/')

def test_wait_for_reload_bad_method():
    spawn_server()
    
    assert post('/api-reloadserver/wait-for-reload').status_code == 405

def test_trigger_reload_exists():
    spawn_server()
    
    assert post('/api-reloadserver/trigger-reload').status_code == 204

def test_trigger_reload_bad_method():
    spawn_server()
    
    assert get('/api-reloadserver/trigger-reload').status_code == 405

def test_reload_by_api():
    spawn_server()
    
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    assert post('/api-reloadserver/trigger-reload').status_code == 204
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_reload_by_api_multiple():
    spawn_server()
    
    threads = [
        threading.Thread(target=wait_for_reload),
        threading.Thread(target=wait_for_reload, kwargs={'index': 1}),
    ]
    for thread in threads: thread.start()
    
    time.sleep(0.1)
    with lock:
        assert wait_for_reload_responses[0] is None
        assert wait_for_reload_responses[1] is None
    
    assert post('/api-reloadserver/trigger-reload').status_code == 204
    for thread in threads: thread.join(2)
    with lock:
        assert wait_for_reload_responses[0] == 204
        assert wait_for_reload_responses[1] == 204

def test_reload_by_api_bad_path():
    spawn_server()
    
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    assert post('/api-reloadserver/trigger-reloadx').status_code == 404
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    assert post('/api-reloadserver/trigger-reload').status_code == 204
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_reload_by_watchdog():
    spawn_server()
    
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('some-file', 'w') as f: f.write('foo')
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_reload_by_watchdog_multiple():
    spawn_server()
    
    threads = [
        threading.Thread(target=wait_for_reload),
        threading.Thread(target=wait_for_reload, kwargs={ 'index': 1 }),
    ]
    for thread in threads: thread.start()
    
    time.sleep(0.1)
    with lock:
        assert wait_for_reload_responses[0] is None
        assert wait_for_reload_responses[1] is None
    
    with open('some-file', 'w') as f: f.write('foo')
    for thread in threads: thread.join(2)
    with lock:
        assert wait_for_reload_responses[0] == 204
        assert wait_for_reload_responses[1] == 204

def test_reload_by_watchdog_ignored_file():
    spawn_server()
    
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('.ignored-file', 'w') as f: f.write('foo')
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('some-file', 'w') as f: f.write('foo')
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_blind():
    spawn_server(blind=True)
    
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('blinded-file', 'w') as f: f.write('foo')
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    assert post('/api-reloadserver/trigger-reload').status_code == 204
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_skip_built_in_ignores():
    spawn_server(skip_built_in_ignores=True)
    
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('.not-hidden', 'w') as f: f.write('foo')
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_watch():
    spawn_server(watch=['*.js'])
    
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('some-script.js', 'w') as f: f.write('foo')
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_watch_multiple():
    spawn_server(watch=['*.html', '*.js'])
    
    for i, filename in enumerate(['some-markup.html', 'some-script.js']):
        thread = threading.Thread(target=wait_for_reload, kwargs={ 'index': i })
        thread.start()
        
        time.sleep(0.1)
        with lock: assert wait_for_reload_responses[i] is None
        
        with open(filename, 'w') as f: f.write('foo')
        thread.join(2)
        with lock: assert wait_for_reload_responses[i] == 204

def test_watch_different_file():
    spawn_server(watch=['*.js'])
    
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('some-ignored-markup.html', 'w') as f: f.write('foo')
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('some-watched-script.js', 'w') as f: f.write('foo')
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_ignore():
    spawn_server(ignore=['*.css'])
    
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('ignored.css', 'w') as f: f.write('foo')
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('watched.js', 'w') as f: f.write('foo')
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204


def test_ignore_multiple():
    spawn_server(ignore=['*.css', '*.md'])
    
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('ignored.css', 'w') as f: f.write('foo')
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('also-ignored.md', 'w') as f: f.write('foo')
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('watched.js', 'w') as f: f.write('foo')
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_script_tag_injected_into_html():
    spawn_server()
    
    with open('test.html', 'w') as f: f.write('<html></html>')
    
    res = get('/test.html')
    assert res.status_code == 200
    assert int(res.headers['Content-Length']) > 13
    assert '<script type="text/javascript">' in res.text
    assert '</script>' in res.text

def test_script_tag_NOT_injected_into_txt():
    spawn_server()
    
    with open('test.txt', 'w') as f: f.write('<html></html>')
    
    res = get('/test.txt')
    assert res.status_code == 200
    assert int(res.headers['Content-Length']) == 13
    assert res.text == '<html></html>'

def test_content_length_rewriting_does_NOT_spill_over():
    spawn_server()
    
    with open('1.html', 'w') as f: f.write('<html></html>')
    with open('2.txt', 'w') as f: f.write('<html></html>')
    
    assert get('/1.html').status_code == 200
    res = get('/2.txt')
    assert res.status_code == 200
    assert int(res.headers['Content-Length']) == 13
    assert res.text == '<html></html>'




# Verify example curl command works
# TODO Update for reload testing
# TODO Also maybe a touch example too
'''def test_curl_example(self):
    spawn_server()
    
    result = subprocess.run([
            'curl', '-X', 'POST', '{}://localhost:8000/upload'.format(PROTOCOL.lower()),
            '--insecure', '-F', 'files=@../test-files/simple-example.txt',
        ],
        stdout=None if VERBOSE else subprocess.DEVNULL,
        stderr=None if VERBOSE else subprocess.DEVNULL,
    )
    
    self.assertEqual(result.returncode, 0)
    
    with open('simple-example.txt') as f_actual, open('../test-files/simple-example.txt') as f_expected:
        self.assertEqual(f_actual.read(), f_expected.read())'''








def spawn_server(port: int | None = None,
    certificate: str | None = ('../server.pem' if PROTOCOL == 'HTTPS' else None),
    watch: list | None = None, ignore: list | None = None,
    skip_built_in_ignores: bool = False, blind: bool = False) -> None:
    args = ['python3', '-u', '-m', 'reloadserver']
    if port: args += [str(port)]
    if certificate: args += ['-c', certificate]
    if watch: args += ['-w'] + watch
    if ignore: args += ['-i'] + ignore
    if skip_built_in_ignores: args += ['--skip-built-in-ignores']
    if blind: args += ['--blind']
    
    server_holder[0] = subprocess.Popen(args)
    
    # Wait for server to finish starting
    for _ in range(10):
        try:
            get('/', port=port or 8000)
            break
        except requests.exceptions.ConnectionError:
            time.sleep(0.01)
    else:
        raise Exception('Port {} not responding. Did the server fail to start?'.format(port or 8000))

def get(path: str | bytes, port: int = 8000, *args, **kwargs) -> requests.Response:
    return requests.get('{}://127.0.0.1:{}{}'.format(PROTOCOL.lower(), port, path),
        verify=False, *args, **kwargs)

def post(path: str | bytes, port: int = 8000, *args, **kwargs) -> requests.Response:
    return requests.post('{}://127.0.0.1:{}{}'.format(PROTOCOL.lower(), port, path),
        verify=False, *args, **kwargs)

def wait_for_reload(index: int = 0) -> None:
    res = get('/api-reloadserver/wait-for-reload')
    with lock: wait_for_reload_responses[index] = res.status_code
