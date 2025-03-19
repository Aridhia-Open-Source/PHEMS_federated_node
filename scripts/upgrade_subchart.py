"""
Simple script that opens the Chart.yaml file and
replaces the given subchart version with the one provided
in input
"""

import logging
import re
import sys
from argparse import ArgumentParser

CHART_FILE = "k8s/federated-node/Chart.yaml"

logger = logging.getLogger("bumper")
logger.setLevel(logging.INFO)

parser = ArgumentParser(
    prog="Subchart Version Bumper",
    description="Upgrades the version of this Chart's dependency"
)

parser.add_argument('-s', '--subchart', required=True, type=str)
parser.add_argument('-v', '--version', required=True)


if __name__ == "__main__":
    args = parser.parse_args()

    with open(CHART_FILE) as f:
        chart_file = f.readlines()

    for idx, line in enumerate(chart_file):
        if re.match(f'.*name: {args.subchart}', line):
            s_idx = idx + 1
            while s_idx < len(chart_file):
                if re.match('.*version:', chart_file[s_idx]):
                    chart_file[s_idx] = re.sub(': .*\n', f': "{args.version}"\n', chart_file[s_idx])
                    break
                if re.match(' +-', chart_file[s_idx]):
                    logger.error("Subchart %s missing version", args.subchart)
                    sys.exit(1)
                s_idx += 1
            break

    if s_idx == len(chart_file):
        logger.error("Subchart %s missing version", args.subchart)
        sys.exit(1)

    with open(CHART_FILE, "w") as f:
        f.write("".join(chart_file))
    logger.info("Successfully updated to %s", args.version)
