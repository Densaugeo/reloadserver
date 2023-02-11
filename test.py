import pytest, os, requests, subprocess, time, urllib3, threading
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

####################
# Setup / Teardown #
####################

def setup_module():
    os.mkdir(Path(__file__).parent / 'test-temp')
    os.chdir(Path(__file__).parent / 'test-temp')
    os.symlink('../reloadserver', 'reloadserver')

def setup_function():
    print()
    
    with lock:
        wait_for_reload_responses[0] = None
        wait_for_reload_responses[1] = None
    
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

@pytest.fixture(autouse=True)
def try_a_fixture(request):
    shell_args = ['python3', '-u', '-m', 'reloadserver']
    if PROTOCOL == 'HTTPS': shell_args += ['-c', '../server.pem']
    
    port = None
    
    if 'fixture_args' in request.keywords:
        kwargs = request.keywords['fixture_args'].kwargs
        
        if 'port' in kwargs:
            port = kwargs['port']
            shell_args += [str(kwargs['port'])]
        if 'watch' in kwargs: shell_args += ['-w'] + kwargs['watch']
        if 'ignore' in kwargs: shell_args += ['-i'] + kwargs['ignore']
        if 'skip_built_in_ignores' in kwargs: shell_args += ['--skip-built-in-ignores']
        if 'blind' in kwargs: shell_args += ['--blind']
    
    server = subprocess.Popen(shell_args)
    
    # Wait for server to finish starting
    for _ in range(10):
        try:
            get('/', port=port or 8000)
            break
        except requests.exceptions.ConnectionError:
            time.sleep(0.01)
    else:
        server.terminate()
        raise Exception('Port {} not responding. Did the server fail to start?'.format(port or 8000))
    
    yield
    
    server.terminate()

#########
# Tests #
#########

# Verify a basic test can run. Most importantly, verify the sleep is long enough for the sever to start
def test_basic():
    assert get('/').status_code == 200

# Verify the --port argument is properly passed to the underlying http.server
@pytest.mark.fixture_args(port=8080)
def test_argument_passthrough():
    assert get('/', port=8080).status_code == 200
    
    with pytest.raises(requests.ConnectionError): get('/')

def test_wait_for_reload_bad_method():
    assert post('/api-reloadserver/wait-for-reload').status_code == 405

def test_trigger_reload_exists():
    assert post('/api-reloadserver/trigger-reload').status_code == 204

def test_trigger_reload_bad_method():
    assert get('/api-reloadserver/trigger-reload').status_code == 405

def test_reload_by_api():
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    assert post('/api-reloadserver/trigger-reload').status_code == 204
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_reload_by_api_multiple():
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
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('some-file', 'w') as f: f.write('foo')
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

def test_reload_by_watchdog_multiple():
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

@pytest.mark.fixture_args(blind=True)
def test_blind():
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

@pytest.mark.fixture_args(skip_built_in_ignores=True)
def test_skip_built_in_ignores():
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('.not-hidden', 'w') as f: f.write('foo')
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

@pytest.mark.fixture_args(watch=['*.js'])
def test_watch():
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    with open('some-script.js', 'w') as f: f.write('foo')
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

@pytest.mark.fixture_args(watch=['*.html', '*.js'])
def test_watch_multiple():
    for i, filename in enumerate(['some-markup.html', 'some-script.js']):
        thread = threading.Thread(target=wait_for_reload, kwargs={ 'index': i })
        thread.start()
        
        time.sleep(0.1)
        with lock: assert wait_for_reload_responses[i] is None
        
        with open(filename, 'w') as f: f.write('foo')
        thread.join(2)
        with lock: assert wait_for_reload_responses[i] == 204

@pytest.mark.fixture_args(watch=['*.js'])
def test_watch_different_file():
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

@pytest.mark.fixture_args(ignore=['*.css'])
def test_ignore():
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

@pytest.mark.fixture_args(ignore=['*.css', '*.md'])
def test_ignore_multiple():
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
    with open('test.html', 'w') as f: f.write('<html></html>')
    
    res = get('/test.html')
    assert res.status_code == 200
    assert int(res.headers['Content-Length']) > 13
    assert '<script type="text/javascript">' in res.text
    assert '</script>' in res.text

def test_script_tag_NOT_injected_into_txt():
    with open('test.txt', 'w') as f: f.write('<html></html>')
    
    res = get('/test.txt')
    assert res.status_code == 200
    assert int(res.headers['Content-Length']) == 13
    assert res.text == '<html></html>'

def test_content_length_rewriting_does_NOT_spill_over():
    with open('1.html', 'w') as f: f.write('<html></html>')
    with open('2.txt', 'w') as f: f.write('<html></html>')
    
    assert get('/1.html').status_code == 200
    res = get('/2.txt')
    assert res.status_code == 200
    assert int(res.headers['Content-Length']) == 13
    assert res.text == '<html></html>'

def test_curl_example():
    thread = threading.Thread(target=wait_for_reload)
    thread.start()
    
    time.sleep(0.1)
    with lock: assert wait_for_reload_responses[0] is None
    
    assert subprocess.run([
            'curl', '--insecure', '-X', 'POST',
            '{}://localhost:8000/api-reloadserver/trigger-reload'.format(PROTOCOL.lower()),
        ],
        stdout=None if VERBOSE else subprocess.DEVNULL,
        stderr=None if VERBOSE else subprocess.DEVNULL,
    ).returncode == 0
    thread.join(2)
    with lock: assert wait_for_reload_responses[0] == 204

###########
# Helpers #
###########

def get(path: str | bytes, port: int = 8000, *args, **kwargs) -> requests.Response:
    return requests.get('{}://127.0.0.1:{}{}'.format(PROTOCOL.lower(), port, path),
        verify=False, *args, **kwargs)

def post(path: str | bytes, port: int = 8000, *args, **kwargs) -> requests.Response:
    return requests.post('{}://127.0.0.1:{}{}'.format(PROTOCOL.lower(), port, path),
        verify=False, *args, **kwargs)

def wait_for_reload(index: int = 0) -> None:
    res = get('/api-reloadserver/wait-for-reload')
    with lock: wait_for_reload_responses[index] = res.status_code
