#!/bin/bash

set -e
python3 -m pip install --no-cache-dir pipenv
cd /app
pipenv check --continue-on-error
