#!/bin/bash

export PYTHONPATH="/app/nexus/operator:/app/nexus/client"
pylint nexus_operator --output /tmp/pylint.txt
