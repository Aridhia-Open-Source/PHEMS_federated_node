#!/bin/bash

export PYTHONPATH="/app/nexus/operator:/app/nexus"
pylint nexus_operator --output /tmp/pylint.txt
