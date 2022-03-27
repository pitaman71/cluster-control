#! env python3

from __future__ import annotations

import typing
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

from . import configurable
from . import resource
from . import file

class RSAKey(resource.Resource):
    bits: configurable.Var[int]
    private: resource.Ref[file.Image]
    public: resource.Ref[file.Image]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.bits = configurable.Var(self, 'bits').select(2048)
        self.private = resource.Ref(self, 'private', file.Image)
        self.public = resource.Ref(self, 'public', file.Image)

    def up(self, phase:resource.Phase):
        super().up(phase)
        if self.public().contents:
            print(f"{self} : RSA key already generated")
            return
        with phase.sub(f"{self} : Generating a new RSA key of {self.bits()} bits with Paramiko") as phase:
            paramiko_key = paramiko.RSAKey.generate(self.bits())
            buf = io.StringIO()
            paramiko_key.write_private_key(buf)
            self.private().load(buf.getvalue())
            self.public().load(paramiko_key.get_base64())

class RootCACredentials(resource.Resource):
    name: configurable.Var[str]
    country: configurable.Var[str]
    state: configurable.Var[str]
    city: configurable.Var[str]
    org: configurable.Var[str]
    division: configurable.Var[str]
    serial: configurable.Var[int]

    key: resource.Ref[RSAKey]
    cert: resource.Ref[file.Image]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.name = configurable.Var(self, 'name')
        self.country = configurable.Var(self, 'country')
        self.state = configurable.Var(self, 'state')
        self.city = configurable.Var(self, 'city')
        self.org = configurable.Var(self, 'org')
        self.division = configurable.Var(self, 'division')
        self.serial = configurable.Var(self, 'serial')

        self.key = resource.Ref(self, 'key', RSAKey)
        self.cert = resource.Ref(self, 'cert', file.Image)

    def get_subject(self):
        return self.get_certificate().get_subject()
        
    def get_certificate(self):
        return crypto.load_certificate(crypto.FILETYPE_PEM, self.cert().contents())

    def up(self, phase: resource.Phase):
        super().up(phase)
        if self.cert().contents:
            print(f"{self} : reusing existing Root CA")
            return 

        if not self.serial:
            self.serial.select(secrets.randbits(64))

        with phase.sub(f"{self} : making a new Root CA") as phase:
            pair = crypto.load_privatekey(crypto.FILETYPE_PEM, self.key().private().contents())
            cert = crypto.X509()
            cert.get_subject().C = self.country()
            cert.get_subject().ST = self.state()
            cert.get_subject().L = self.city()
            cert.get_subject().O = self.org()
            cert.get_subject().OU = self.division()
            cert.get_subject().CN = self.name()
            cert.set_serial_number(self.serial())
            cert.gmtime_adj_notBefore(0)
            cert.gmtime_adj_notAfter(365*24*3600) # 365 days in seconds
            cert.set_issuer(cert.get_subject())
            cert.set_pubkey(pair)
            cert.sign(pair, 'sha256')
            signed = crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode('utf-8')
            self.cert().load(signed)

class ServerCredentials(resource.Resource):
    authority: configurable.Var[RootCACredentials]
    serial: configurable.Var[int]

    key: resource.Ref[RSAKey]
    cert: resource.Ref[file.Image]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.authority = configurable.Var(self, 'authority')
        self.key = resource.Ref(self, 'key', RSAKey)
        self.cert = resource.Ref(self, 'cert', file.Image)
        self.serial = configurable.Var(self, 'serial')
        
    def up(self, phase: resource.Phase):
        super().up(phase)
        if self.cert().contents:
            print(f"{self} : reusing server credentials")
            return

        with phase.sub(f"{self} : creating new server credentials") as phase:
            csr = crypto.X509Req()
            authority = self.authority()
            if not self.name:
                raise RuntimeError("name is not set")

            csr.get_subject().CN = self.name
            csr.get_subject().countryName = authority.name()
            csr.get_subject().stateOrProvinceName = authority.state()
            csr.get_subject().localityName = authority.city()
            csr.get_subject().organizationName = authority.org()
            csr.get_subject().organizationalUnitName = authority.division()
            san_list = ["DNS:" + self.name]
            authority_cert = crypto.load_certificate(crypto.FILETYPE_PEM, authority.cert().contents())

            csr.add_extensions([ 
                crypto.X509Extension( 'authorityKeyIdentifier'.encode(), True, 'issuer'.encode(), issuer=authority_cert),
                crypto.X509Extension( 'basicConstraints'.encode(), False, 'CA:FALSE'.encode()),
                crypto.X509Extension( 'keyUsage'.encode(), False, 'digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment'.encode()),
                crypto.X509Extension( 'subjectAltName'.encode(), False, ", ".join(san_list).encode() ) 
            ] )

            pair = crypto.load_privatekey(crypto.FILETYPE_PEM, self.key().private().contents())
            csr.set_pubkey(pair)
            csr.sign(pair, 'sha256')

            cert = crypto.X509()
            cert.set_serial_number(self.serial())
            cert.gmtime_adj_notBefore(0)
            cert.gmtime_adj_notAfter(365*24*3600) # 365 days in seconds
            cert.set_issuer(authority_cert.get_subject())
            cert.set_subject(csr.get_subject())
            cert.add_extensions(csr.get_extensions())
            cert.set_pubkey(csr.get_pubkey())

            cert.sign(pair, 'sha256')

            self.cert().load(crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode('utf-8'))
            if not self.cert().contents:
                raise RuntimeError(f'Unable to dump this certificate: {str(cert)}')
