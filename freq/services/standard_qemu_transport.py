"""Ordinary bounded stdlib read transport; no application admission authority.

The original application retains this attempt before run and independently
owns session/configuration/credential/trust/target/writer/recipient admission.
Only fixed paths and a configured literal IP are supported. No resolver,
redirect, proxy, retry, arbitrary URL, worker or provider mutation exists here.
Cooperative deadlines do not cancel an entered native call or prove closure.
"""
import ipaddress
import json
import math
import re
import socket
import ssl
import threading
import time


AGGREGATE_BODY_LIMIT = 4194304
_CAPS = {'cluster':262144, 'inventory':1048576, 'status':262144,
         'configuration':1048576, 'agent-network':1048576}
_NODE = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,62}\Z')
_HEADER_NAME = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")


class ReadUnavailable(Exception):
    def __init__(self):super().__init__('Read unavailable')


class ReadUnsettled(Exception):
    def __init__(self):super().__init__('Read unresolved')


def _bad():raise ReadUnavailable() from None


def _first(first,later):
    if (first is None or
        (issubclass(type(first),Exception) and not issubclass(type(later),Exception)) or
        (issubclass(type(first),Exception) and not issubclass(type(first),MemoryError)
         and issubclass(type(later),MemoryError))):return later
    return first


class ReadBudget:
    """One original request's shared sibling accounting, not permission/quota."""
    __slots__=('_end','_consumed','_thread')
    def __init__(self,end):
        if type(self) is not ReadBudget or hasattr(self,'_end'):_bad()
        now=time.monotonic()
        if type(end) is not float or not math.isfinite(end) or not now < end <= now+10.0:_bad()
        self._end=end;self._consumed=0;self._thread=threading.get_ident()

    @property
    def end(self):return self._end

    @property
    def consumed(self):return self._consumed

    def __init_subclass__(cls,**kwargs):raise TypeError('Read budgets cannot be subclassed')
    def __copy__(self):raise TypeError('Read budgets cannot be copied')
    def __deepcopy__(self,memo):raise TypeError('Read budgets cannot be copied')
    def __reduce_ex__(self,protocol):raise TypeError('Read budgets cannot be serialized')

    def remaining(self):
        if threading.get_ident()!=self._thread:_bad()
        value=self._end-time.monotonic()
        if value<=0:_bad()
        return value

    def charge(self,count):
        self.remaining()
        if type(count) is not int or count<0 or self.consumed+count>AGGREGATE_BODY_LIMIT:_bad()
        self._consumed+=count  # Never refunded by rejection/retirement/cleanup.


def _path(kind,node,vmid):
    if type(kind) is not str or kind not in _CAPS or type(node) is not str or not _NODE.fullmatch(node):_bad()
    base='/api2/json/nodes/'+node
    if kind in ('cluster','inventory'):
        if vmid is not None:_bad()
        return '/api2/json/cluster/status' if kind=='cluster' else base+'/qemu'
    if type(vmid) is not int or not 100<=vmid<=999999999:_bad()
    base+='/qemu/'+str(vmid)
    return base+{'status':'/status/current','configuration':'/config?current=1',
                 'agent-network':'/agent/network-get-interfaces'}[kind]


def _pairs(values):
    result={}
    for key,value in values:
        if key in result:_bad()
        result[key]=value
    return result


def _integer(value):
    if len(value)>32:_bad()
    return int(value)


def _float(value):
    result=float(value)
    if not math.isfinite(result):_bad()
    return result


def _constant(value):_bad()


def decode_provider_body(body):
    """Strict private provider envelope; schema projection remains separate."""
    if type(body) is not bytes or not 1<=len(body)<=AGGREGATE_BODY_LIMIT:_bad()
    depth=0;quoted=escaped=False
    for byte in body:
        if quoted:
            if escaped:escaped=False
            elif byte==92:escaped=True
            elif byte==34:quoted=False
        elif byte==34:quoted=True
        elif byte in (91,123):
            depth+=1
            if depth>32:_bad()
        elif byte in (93,125):
            depth-=1
            if depth<0:_bad()
    if quoted or depth:_bad()
    failed=False
    try:
        value=json.loads(body.decode('utf-8'),object_pairs_hook=_pairs,
            parse_int=_integer,parse_float=_float,parse_constant=_constant)
    except (ValueError,UnicodeError,RecursionError,ReadUnavailable):failed=True
    if failed:_bad()  # Outside parser handler: no JSON.doc chained outward.
    if type(value) is not dict or set(value)!={'data'}:_bad()
    return value['data']


def _recv(sock,count,budget):
    sock.settimeout(budget.remaining())
    result=sock.recv(count)
    budget.remaining()
    return result


def _read_http(sock,budget,cap):
    buffered=bytearray();header_bytes=0
    def line():
        nonlocal header_bytes
        while True:
            index=buffered.find(b'\r\n')
            if index>=0:
                if index>4096:_bad()
                result=bytes(buffered[:index]);del buffered[:index+2]
                header_bytes+=index+2
                if header_bytes>16384 or b'\r' in result or b'\n' in result:_bad()
                return result
            if len(buffered)>4096 or header_bytes+len(buffered)>=16384:_bad()
            part=_recv(sock,min(4096,16384-header_bytes-len(buffered)),budget)
            if not part:_bad()
            buffered.extend(part)
    status=line()
    if not re.fullmatch(rb'HTTP/1\.[01] 200 [\x20-\x7e]{0,128}',status):_bad()
    headers={}
    for _ in range(65):
        row=line()
        if not row:break
        if len(headers)>=64 or b':' not in row:_bad()
        name,value=row.split(b':',1);name=name.lower()
        if not _HEADER_NAME.fullmatch(name) or name in headers:_bad()
        value=value.strip(b' \t')
        if any(byte<32 or byte>126 for byte in value):_bad()
        headers[name]=value
    else:_bad()
    # This first profile deliberately requires Content-Length, not EOF/chunk
    # framing. Compatibility is qualified later; never retry another profile.
    length=headers.get(b'content-length',b'')
    if not re.fullmatch(rb'[0-9]{1,8}',length):_bad()
    length=int(length)
    if not 1<=length<=cap or budget.consumed+length>AGGREGATE_BODY_LIMIT:_bad()
    if b'transfer-encoding' in headers or b'trailer' in headers:_bad()
    if headers.get(b'content-encoding',b'identity').lower()!=b'identity':_bad()
    if headers.get(b'connection',b'close').lower()!=b'close':_bad()
    content_type=headers.get(b'content-type',b'').lower()
    if content_type not in (b'application/json',b'application/json; charset=utf-8',b'application/json;charset=utf-8'):_bad()
    if len(buffered)>length:_bad()
    budget.charge(len(buffered));body=buffered
    while len(body)<length:
        part=_recv(sock,min(65536,length-len(body)),budget)
        if not part:_bad()
        budget.charge(len(part));body.extend(part)
    if _recv(sock,1,budget):_bad()  # No pipeline/trailing bytes on this connection.
    result=decode_provider_body(bytes(body));budget.remaining()
    return result


class FixedReadAttempt:
    """Retain before run. Supplied source values never grant original authority."""
    __slots__=('_ip','_family','_address','_host','_ca','_authorization','_path',
               '_cap','_budget','_thread','_started','_context','_raw','_tls',
               '_stages','_errors','_failure','_state','_result')
    def __init__(self,recipient,ca_pem,authorization,kind,node,vmid,budget):
        if type(self) is not FixedReadAttempt or hasattr(self,'_started'):_bad()
        if type(recipient) is not str or len(recipient)>45 or '%' in recipient:_bad()
        failed=False
        try:ip=ipaddress.ip_address(recipient)
        except ValueError:failed=True
        if failed or str(ip)!=recipient or ip.is_unspecified or ip.is_multicast:_bad()
        if type(ca_pem) is not bytes or not 1<=len(ca_pem)<=1048576:_bad()
        failed=False
        try:ca=ca_pem.decode('ascii')
        except UnicodeError:failed=True
        if failed:_bad()
        if (type(authorization) is not bytes or not 1<=len(authorization)<=4096
                or not authorization.startswith(b'PVEAPIToken=')
                or any(byte<33 or byte>126 for byte in authorization)):_bad()
        if type(budget) is not ReadBudget:_bad()
        path=_path(kind,node,vmid)
        self._ip=recipient;self._family=socket.AF_INET if ip.version==4 else socket.AF_INET6
        self._address=(recipient,8006) if ip.version==4 else (recipient,8006,0,0)
        self._host=recipient if ip.version==4 else '['+recipient+']'
        self._ca=ca;self._authorization=authorization;self._path=path
        self._cap=_CAPS[kind];self._budget=budget;self._thread=threading.get_ident()
        self._started=False;self._context=self._raw=self._tls=None
        self._stages={key:'unused' for key in ('context','ca','socket','connect','tls','handshake','send','receive','tls-close','raw-close')}
        self._errors=[None]*3;self._failure=None;self._state='prepared';self._result=None

    def __init_subclass__(cls,**kwargs):raise TypeError('Read attempts cannot be subclassed')
    def __copy__(self):raise TypeError('Read attempts cannot be copied')
    def __deepcopy__(self,memo):raise TypeError('Read attempts cannot be copied')
    def __reduce_ex__(self,protocol):raise TypeError('Read attempts cannot be serialized')

    def _emit(self):
        error=self._failure
        if error is not None and (not issubclass(type(error),Exception) or issubclass(type(error),MemoryError)):raise error
        if self._state=='unsettled':raise ReadUnsettled() from None
        raise ReadUnavailable() from None

    def run(self):
        if type(self) is not FixedReadAttempt or threading.get_ident()!=self._thread:_bad()
        if self._started:self._emit()
        self._started=True;self._state='entered';stage=self._stages;budget=self._budget
        try:
            budget.remaining();stage['context']='entered'
            self._context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);stage['context']='returned'
            self._context.check_hostname=True;self._context.verify_mode=ssl.CERT_REQUIRED
            self._context.minimum_version=ssl.TLSVersion.TLSv1_2
            self._context.keylog_filename=None
            budget.remaining();stage['ca']='entered'
            self._context.load_verify_locations(cadata=self._ca);stage['ca']='returned'
            budget.remaining();stage['socket']='entered'
            self._raw=socket.socket(self._family,socket.SOCK_STREAM);stage['socket']='returned'
            self._raw.settimeout(budget.remaining());stage['connect']='entered'
            self._raw.connect(self._address);stage['connect']='returned'
            self._raw.settimeout(budget.remaining());stage['tls']='entered'
            self._tls=self._context.wrap_socket(self._raw,server_hostname=self._ip,do_handshake_on_connect=False)
            stage['tls']='returned';self._tls.settimeout(budget.remaining());stage['handshake']='entered'
            self._tls.do_handshake();stage['handshake']='returned'
            request=(b'GET '+self._path.encode('ascii')+b' HTTP/1.1\r\nHost: '+
                self._host.encode('ascii')+b':8006\r\nAuthorization: '+self._authorization+
                b'\r\nAccept: application/json\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n')
            self._tls.settimeout(budget.remaining());stage['send']='entered'
            self._tls.sendall(request);stage['send']='returned';stage['receive']='entered'
            self._result=_read_http(self._tls,budget,self._cap);stage['receive']='returned'
        except BaseException as error:
            self._errors[0]=error;self._failure=error
        for index,(name,handle) in enumerate((('tls-close',self._tls),('raw-close',self._raw)),1):
            if handle is not None:
                stage[name]='entered'
                try:handle.close();stage[name]='returned'
                except BaseException as error:
                    self._errors[index]=error;self._failure=_first(self._failure,error)
        if self._failure is not None:
            self._state='unsettled' if 'entered' in stage.values() else 'refused'
            self._emit()
        # Parsing and independent cleanup may consume the remaining budget.
        # Final application session/source/recipient admission still follows.
        try:budget.remaining()
        except BaseException as error:
            self._errors[0]=error;self._failure=error;self._state='refused';self._emit()
        self._state='observed'
        return self._result
