#! env python3

from __future__ import annotations

from typing import List, Dict
import abc

import json
import boto3
import secrets
import sys
import os
import io
import stat
import base64
import urllib
import time
import subprocess
import tempfile
import traceback
import paramiko
from OpenSSL import crypto

import resource
import blob

class RSAKey(resource.Resource):
    """Resource representing a 2048 bit RSA key pair in SSH format"""
    def __init__(self, name:str=None, bits:int=2048):
        self.name = name
        self.bits = bits
        self.private_key_data = None
        self.private_key_file = None
        self.public_key_data = None
        self.paramiko_key = None
        
    def plan(self):
        pass
    
    def get_private_key_file(self):
        if self.private_key_file is None and self.private_key_data is not None:
            self.private_key_file = self.name + '.pem'
            with open(self.private_key_file, 'wt') as fp:
                fp.write(self.private_key_data)
        return self.private_key_file

    def up(self, top):
        if self.paramiko_key is None:
            if self.private_key_data is not None:
                print(f"{self.__class__.__qualname__}.up : reusing private key data")
                buf = io.StringIO(self.private_key_data)
                self.paramiko_key = paramiko.RSAKey.from_private_key(buf)
            else:
                print(f"{self.__class__.__qualname__}.up : generating new private key")
                self.paramiko_key = paramiko.RSAKey.generate(self.bits)
        if self.private_key_data is None and self.paramiko_key is not None:
            print(f"{self.__class__.__qualname__}.up : extracting private key data")
            buf = io.StringIO()
            self.paramiko_key.write_private_key(buf)
            self.private_key_data = buf.getvalue()
        if self.public_key_data is None and self.paramiko_key is not None:
            self.public_key_data = self.paramiko_key.get_base64()
        top.save()

    def down(self, top):
        self.paramiko_key = None
        if self.private_key_data is not None:
            print(f"{self.__class__.__qualname__}.down : deleting private key data")
            self.private_key_data = None
            top.save()

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('name')
        visitor.inline('bits')
        visitor.inline('private_key_data')
        visitor.endObject(self)

class RSAKey2(resource.Resource):
    """Resource representing a 2048 bit RSA key pair in SSH format"""
    def __init__(self, name:str=None, bits:int=2048):
        self.name = name
        self.bits = bits
        self.private_key_file = None
        self.public_key_data = None
        self.paramiko_key = None
        
    def plan(self):
        if self.private_key_file is None:
            self.private_key_file = blob.File(self.name, 'key')
    
    def get_private_key_file(self):
        return self.private_key_file

    def get_pair(self):
        return crypto.load_privatekey(crypto.FILETYPE_PEM, self.private_key_file.contents.encode('utf-8'))

    def up(self, top):
        if self.private_key_file.is_loaded():
            print(f"{self.__class__.__qualname__}.up({self.name}) : reusing private key data")
        else:
            print(f"{self.__class__.__qualname__}.up({self.name}) : generating new private key")
            k = crypto.PKey()
            k.generate_key(crypto.TYPE_RSA, 2048)
            self.private_key_file.load(crypto.dump_privatekey(crypto.FILETYPE_PEM, k).decode('utf-8'))
            self.public_key_data = crypto.dump_publickey(crypto.FILETYPE_PEM, k).decode('utf-8')
            top.save()

    def down(self, top):
        self.private_key_file.down()
        if self.public_key_data is not None:
            self.public_key_data = None
            top.save()

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('name')
        visitor.inline('bits')
        visitor.inline('private_key_file')
        visitor.inline('public_key_data')
        visitor.endObject(self)

class RootCACredentials:
    def __init__(self, name:str=None, country:str=None, state:str=None, city:str=None, org:str=None, division:str=None):
        self.name = name
        self.country = country
        self.state = state
        self.city = city
        self.org = org
        self.division = division

        self.serial = None
        self.key:RSAKey2 = None
        self.cert:blob.File = None
    
    def plan(self):
        if self.key is None:
            self.key = RSAKey2(self.name+'-key')
        self.key.plan()
        if self.cert is None:
            self.cert = blob.File(self.name, 'cert')
        self.cert.plan()

    def get_subject(self):
        return self.get_certificate().get_subject()

    def get_certificate(self):
        return crypto.load_certificate(crypto.FILETYPE_PEM, self.cert.contents)

    def get_private_key(self):
        return crypto.load_privatekey(crypto.FILETYPE_PEM, self.key.private_key_file.contents)

    def up(self, top):
        self.key.up(top)
        self.cert.up(top)
        if self.serial is None:
            self.serial = secrets.randbits(64)
        if self.cert.is_loaded():
            print(f"{self.__class__.__qualname__}.up : reusing existing Root CA")
        else:
            print(f"{self.__class__.__qualname__}.up : making a new Root CA")
            k = self.key.get_pair()
            cert = crypto.X509()
            cert.get_subject().C = self.country
            cert.get_subject().ST = self.state
            cert.get_subject().L = self.city
            cert.get_subject().O = self.org
            cert.get_subject().OU = self.division
            cert.get_subject().CN = self.name
            cert.set_serial_number(self.serial)
            cert.gmtime_adj_notBefore(0)
            cert.gmtime_adj_notAfter(365*24*3600) # 365 days in seconds
            cert.set_issuer(cert.get_subject())
            cert.set_pubkey(k)
            cert.sign(k, 'sha256')
            signed = crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode('utf-8')
            self.cert.load(signed)

    def down(self, top):
        if self.cert is not None:
            print(f"{self.__class__.__qualname__}.up : discarding Root CA")
            self.cert = None
            top.save()
        if self.key is not None:
            self.key.down(top)
            top.save()

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('name')
        visitor.inline('country')
        visitor.inline('state')
        visitor.inline('city')
        visitor.inline('org')
        visitor.inline('division')
        visitor.inline('serial')
        visitor.inline('key')
        visitor.inline('cert')
        visitor.endObject(self)

class ServerCredentials:
    def __init__(self, name:str=None, authority: RootCACredentials=None):
        self.name = name
        self.authority = authority
        self.serial = None
        self.key:RSAKey2 = None
        self.cert:blob.File = None

    def plan(self):
        if self.key is None:
            self.key = RSAKey2(self.name+'-key')
        self.key.plan()
        if self.cert is None:
            self.cert = blob.File(self.name, 'cert')
        self.cert.plan()

    def get_certificate_file(self):
        return self.cert

    def get_private_key_file(self):
        return self.key.get_private_key_file()
        
    def up(self, top):
        if self.serial is None:
            self.serial = secrets.randbits(64)
        self.key.up(top)
        self.cert.up(top)
        if self.cert.is_loaded():
            print(f"{self.__class__.__qualname__}.up : reusing server credentials")
        else:
            print(f"{self.__class__.__qualname__}.up : creating server credentials")
            csr = crypto.X509Req()
            csr.get_subject().CN = self.name
            csr.get_subject().countryName = self.authority.country
            csr.get_subject().stateOrProvinceName = self.authority.state
            csr.get_subject().localityName = self.authority.city
            csr.get_subject().organizationName = self.authority.org
            csr.get_subject().organizationalUnitName = self.authority.division
            san_list = ["DNS:" + self.name]
            csr.add_extensions([ 
                crypto.X509Extension( 'authorityKeyIdentifier'.encode(), True, 'issuer'.encode(), issuer=self.authority.get_certificate()),
                crypto.X509Extension( 'basicConstraints'.encode(), False, 'CA:FALSE'.encode()),
                crypto.X509Extension( 'keyUsage'.encode(), False, 'digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment'.encode()),
                crypto.X509Extension( 'subjectAltName'.encode(), False, ", ".join(san_list).encode() ) 
            ] )

            csr.set_pubkey(self.key.get_pair())
            print(f"DEBUG: CSR extension count before signing: {len(csr.get_extensions())}")
            csr.sign(self.key.get_pair(), 'sha256')
            print(f"DEBUG: CSR extension count after signing: {len(csr.get_extensions())}")

            cert = crypto.X509()
            cert.set_serial_number(self.serial)
            cert.gmtime_adj_notBefore(0)
            cert.gmtime_adj_notAfter(365*24*3600) # 365 days in seconds
            cert.set_issuer(self.authority.get_certificate().get_subject())
            cert.set_subject(csr.get_subject())
            cert.add_extensions(csr.get_extensions())
            cert.set_pubkey(csr.get_pubkey())

            print(f"DEBUG: CERT extension count before signing: {cert.get_extension_count()}")
            cert.sign(self.authority.get_private_key(), 'sha256')
            print(f"DEBUG: CERT extension count after signing: {cert.get_extension_count()}")

            self.cert.load(crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode('utf-8'))
            if not self.cert.is_loaded():
                raise RuntimeError(f'Unable to dump this certificate: {str(cert)}')
            top.save()

    def down(self, top):
        if self.cert is not None:
            print(f"{self.__class__.__qualname__}.up : discarding server credentials")
            self.cert = None
            top.save()
        if self.key is not None:
            self.key.down(top)
            top.save()

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('name')
        visitor.inline('authority')
        visitor.inline('key')
        visitor.inline('cert')
        visitor.endObject(self)
