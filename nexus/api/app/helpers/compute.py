import re

from app.helpers.const import CPU_RESOURCE_REGEX, MEMORY_RESOURCE_REGEX, MEMORY_UNITS
from app.helpers.exceptions import InvalidRequest


def validate_cpu_resources(limit_value: str, request_value: str):
    """
    Given a value for the cpu limits or requests, make sure it conforms to
    accepted k8s values.
    e.g.
        - 100m
        - 0.1
        - 1
    """
    for value in [limit_value, request_value]:
        if value is None or value == "":
            return
        cpu_error_message = f"Cpu resource value {value} not valid."
        if not re.fullmatch(CPU_RESOURCE_REGEX, value):
            raise InvalidRequest(cpu_error_message)
    if convert_cpu_values_to_int(limit_value) < convert_cpu_values_to_int(request_value):
        raise InvalidRequest("Cpu limit cannot be lower than request")


def validate_memory_resources(limit_value: str, request_value: str):
    """
    Given a value for the memory limits or requests, make sure it conforms to
    accepted k8s values.
    e.g.
        - 128974848
        - 129e6
        - 129M
        - 128974848000m
        - 123Mi
    """
    for value in [limit_value, request_value]:
        if value is None or value == "":
            return
        memory_error_msg = f"Memory resource value {value} not valid."
        if not re.fullmatch(MEMORY_RESOURCE_REGEX, value):
            raise InvalidRequest(memory_error_msg)
    if convert_memory_values_to_int(limit_value) < convert_memory_values_to_int(request_value):
        raise InvalidRequest("Memory limit cannot be lower than request")


def convert_cpu_values_to_int(val: str) -> float:
    """
    Since cpu values can come with different units,
    they should be standardized to float, so that they can
    be compared and validated to have limits > requests
    """
    if re.match(r'^\d+$', val):
        return float(val)
    if re.match(r'^\d+\.\d+$', val):
        return float(val)
    return float(val[:-1]) / 1000


def convert_memory_values_to_int(val: str) -> int:
    """
    Since memory values can come with different units,
    they should be standardized to int, so that they can
    be compared and validated to have limits > requests
    """
    if re.match(r'^\d+$', val):
        return int(val)
    if re.match(r'^\d+e\d+$', val):
        base, exp = val.split('e')
        return int(base) * 10**(int(exp))

    # Other accepted formats trail with some letters
    unit_index = re.search(r'[^\d]+$', val).span()[0]
    base = val[:unit_index]
    unit = val[unit_index:]
    return int(base) * MEMORY_UNITS[unit]
