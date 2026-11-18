"""Fixed private provider projections for the schema3 read journey.

No source choice, request, identity, section-success claim or publication grant.
Inputs are the exact built-in DATA from the separately owned strict transport.
An actual original application still must admit/collect/classify/final-release.
"""
import math

from freq.services.guest_profile_formats import guest_config as configuration


class ProjectionUnavailable(Exception):
    def __init__(self):super().__init__('Observation unavailable')


def _bad():raise ProjectionUnavailable() from None


def _literal(value,maximum,nullable=True):
    if value is None and nullable:return None
    if type(value) is not str:_bad()
    failed=False
    try:size=len(value.encode('utf-8'))
    except UnicodeError:failed=True
    if failed or size>maximum or any(ord(char)<32 or 127<=ord(char)<=159 for char in value):_bad()
    return value


def _integer(value):
    if value is None:return None
    if type(value) is not int or not 0<=value<=9007199254740991:_bad()
    return value


def status_data(value):
    if type(value) is not dict or len(value)>256 or any(type(key) is not str for key in value):_bad()
    state=_literal(value.get('status'),64)
    cpu=value.get('cpu')
    if cpu is not None:
        if type(cpu) not in (int,float) or not 0<=cpu<=1 or not math.isfinite(cpu):_bad()
        cpu=float(cpu)
    return dict(state=state,cpu_fraction=cpu,memory_used_bytes=_integer(value.get('mem')),
                memory_limit_bytes=_integer(value.get('maxmem')))


def _mode(fields,key):
    if key not in fields:return None
    value=fields[key]
    if value=='dhcp' or (key=='ip6' and value=='auto'):return value
    # The conservative fixed address parser separately verifies this static
    # value; do not synthesize a mode/address for an absent provider field.
    return 'static'


def configured_network_data(value):
    if type(value) is not dict or len(value)>4096 or any(type(key) is not str for key in value):_bad()
    nets={};ips={};failed=False
    try:
        for key,item in value.items():
            if len(key)>128:_bad()
            prefix='ipconfig' if key.startswith('ipconfig') else 'net' if key.startswith('net') else None
            suffix=key[len(prefix):] if prefix is not None else ''
            if prefix is not None and suffix.isascii() and suffix.isdigit():
                index=configuration.unsigned_text(suffix,31)
                if type(item) is not str:_bad()
                if prefix=='net':
                    nets[index]=(key,configuration.nic(item))
                else:
                    fields=configuration.properties(item)
                    addresses,gateways=configuration.configured_addresses(item)
                    ips[index]=(_mode(fields,'ip'),_mode(fields,'ip6'),addresses,gateways)
            elif prefix is not None:
                # A malformed/unsupported apparent NIC index cannot be silently
                # dropped and still described as complete configured networking.
                _bad()
            elif type(item) in (dict,list):
                _bad()
        if not set(ips)<=set(nets):_bad()
        result=[]
        for index,(key,row) in nets.items():
            ipv4,ipv6,addresses,gateways=ips.get(index,(None,None,[],[]))
            if len(addresses)>16 or len(gateways)>2:_bad()
            result.append(dict(key=key,model=row['model'],mac=row['mac'],
                bridge=row['bridge'],vlan=row['vlan'],ipv4_mode=ipv4,ipv6_mode=ipv6,
                addresses=addresses,gateways=gateways))
        return result
    except (configuration.Refused,ProjectionUnavailable):failed=True
    if failed:_bad()  # No provider strings/exception text chained outward.
