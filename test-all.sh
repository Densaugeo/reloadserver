#!/bin/bash
set -euf -o pipefail

make test PY=python3.11 VERBOSE=0
make test PY=python3.11 VERBOSE=0 PROTOCOL=HTTPS
