# reloadserver

HTTP(S) server with automatic refresh on file changes, based on Python\'s http.server 

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://mit-license.org/)
[![Build Status](https://travis-ci.com/Densaugeo/reloadserver.svg?branch=main)](https://travis-ci.com/github/Densaugeo/reloadserver)

## Supported Platforms

| Platform | Supported? | Notes |
|-|-|-|
| Python 3.10+ | Yes | Tested on 3.10 through 3.12 every release. |
| Python 3.9- | No | |
| Linux | Yes | Tested on Fedora and Ubuntu every release. |
| Windows | Yes | Occasional manual testing. Some features unavailable. |
| Mac | No | I don't have a Mac. It might partially work, but I don't know. |

## Installation

~~~
python3 -m pip install --user reloadserver
~~~

## Usage

~~~
python3 -m reloadserver
~~~

Accepts the same `port` and `bind` arguments as [http.server](https://docs.python.org/3/library/http.server.html), though the others differ. For a full list, run `python -m reloadserver -h`.

By default, monitors files in the current folder (and subfolders) for changes, and refreshes connected clients when a change is detected. Dotfiles and some commonly ignored folders are ignored (this is configurable, as described later). The monitoring is done by injecting a script tag into `.html` files as they're served. This script calls back to reloadserver via long-polling and triggers a reload when it gets the right response.

On Firefox, a full reload is triggered that bypasses cache, as if ctrl+F5 were pressed. Unfortunately, this ability is not available in other browsers (https://developer.mozilla.org/en-US/docs/Web/API/Location/reload).

## File Selection

Files to watch or ignore can be specified, as in these examples:
~~~
# Reload only when index.html or index.js changes
python3 -m reloadserver --watch index.html index.js

# Do not reload when any file in temp cahnges
python3 -m reloadserver --ignore 'temp/*'
~~~

## Trigger Reload by HTTP Request

If your workflow makes file watching complicated (or if you you want to use reloadserver on Windows where file watching doesn't work), a reload can be triggered by sending a `POST` to `/api-reloadserver/trigger-reload`:
~~~
curl -X POST http://localhost:8000/api-reloadserver/trigger-reload
~~~

## HTTPS Option

Why would you need HTTPS for a development environment? Because someone (who is an asshole) decided that several browser APIs such as gamepad and accelerometer APIs should only be available to pages served over HTTPS. So now my development environment needs have HTTPS, which is a headache, and part of why I needed a new reloading server instead of sticking with the existing livereload module for Python.

Run with HTTPS:
~~~
# Generate self-signed server certificate
openssl req -x509 -out server.pem -keyout server.pem -newkey rsa:2048 -nodes -sha256 -subj '/CN=server'

python3 -m reloadserver 8443 --certificate server.pem
~~~

Note: This uses a self-signed server certificate which clients such as web browser and cURL will warn about. Most browsers will allow you to proceed after adding an exception, and cURL will work if given the `-k`/`--insecure` option. Using your own certificate from a certificate authority will avoid these warnings.

## If Behind a Reverse Proxy

When run behind a reverse proxy, needs to handle serving any `.html` files that you want to automatically refresh (so it can inject a script tag), and needs `/api-realoadserver/*`.

If using Caddy, reloadserver works with this Caddyfile (replace HOSTNAME with your test server's name):
~~~
{
  # Not necessary, I just don't like the admin API
  admin off
}

http://:8080 {
  file_server browse
  root * .
  
  @html {
    path *.html
  }
  
  reverse_proxy /api-reloadserver/* http://localhost:8000
  reverse_proxy @html http://localhost:8000
}

https://HOSTNAME:8443 {
  tls internal
  
  file_server browse
  root * .
  
  @html {
    path *.html
  }
  
  reverse_proxy /api-reloadserver/* http://localhost:8000
  reverse_proxy @html http://localhost:8000
}
~~~

## Acknowledgements

Much of `main()` was copied from Python's `http.server`. Many other elements were copied from https://github.com/Densaugeo/uploadserver (another of my projects), thanks to all the contributors over there too!

Thanks to kwyntes for the first pull requests! (Improved handling of malformed .html files and added debouncing).
