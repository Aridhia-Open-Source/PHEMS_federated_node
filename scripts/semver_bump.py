import re
import sys
from argparse import ArgumentParser


CHART_PATH = "./k8s/federated-node/Chart.yaml"
DIGIT_DOT_REGEX = r'\d+.\d+.\d*'

parser = ArgumentParser(
    prog="Semver version bumper",
    description="Upgrades the semver version provided in input"
)

parser.add_argument('-v', '--version', required=True, type=str)
parser.add_argument('-m', '--major', required=False, action='store_true')
parser.add_argument('-n', '--minor', required=False, action='store_true')
parser.add_argument('-p', '--patch', required=False, action='store_true')


def bump_version(current_version:str, major:bool=False, minor:bool=True, patch:bool=False):
  dotted_version = re.findall(DIGIT_DOT_REGEX, current_version)[0]
  int_version = [int(v) for v in dotted_version.split('.')]
  if len(int_version) == 2 and patch:
    print("Patch version cannot be changed as the format does not have one")
    sys.exit(1)

  if major:
    int_version[0] += 1
  if minor:
    int_version[1] += 1
  if patch:
    int_version[2] += 1
  return re.sub(DIGIT_DOT_REGEX, ".".join([str(int_v) for int_v in int_version]), current_version)


if __name__ == "__main__":
  args = parser.parse_args()
  if not re.findall(DIGIT_DOT_REGEX, args.version):
    print("Not a valid format")
    sys.exit(1)

  print(bump_version(args.version, args.major, args.minor, args.patch))
