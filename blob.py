#! env python3

from __future__ import annotations

from typing import List, Dict
import abc

import os
import urllib

import resource

class Peer:
    @abc.abstractmethod
    def get(self, remote_path: str, local: str|File, timeout: int):
        raise RuntimeError(f'Method is not implemented in class {self.__class__.__qualname__}')

    @abc.abstractmethod
    def put(self, local: str|File, remote_path: str, timeout:int, sudo=False, chmod:str=None):
        raise RuntimeError(f'Method is not implemented in class {self.__class__.__qualname__}')

class File(resource.Resource):
    """Resource representing a file in the local filesystem or readable from a URL"""
    def __init__(self, name:str=None, extension: str=None, from_url: str=None):
        self.name = name
        self.extension = extension
        self.from_url = from_url
        self.contents = None

    def plan(self):
        pass

    def up(self, top):
        if self.contents is not None:
            print(f"{self.__class__.__qualname__}({self.filename()}).up : contents are already loaded")
        elif self.from_url is not None:
            if os.path.exists(self.from_url):
                print(f"{self.__class__.__qualname__}({self.filename()}).up : Reading {self.filename()} from {self.from_url}")
                self.load(open(self.from_url, 'rt').read())
            else:
                print(f"{self.__class__.__qualname__}({self.filename()}).up : Fetching {self.filename()} from {self.from_url}")
                lines = [ line.decode('utf-8') for line in urllib.request.urlopen(self.from_url) ]
                self.load(''.join(lines))
        elif not os.path.exists(self.filename()):
            print(f"{self.__class__.__qualname__}({self.filename()}).up : file does not exist")
        else:
            print(f"{self.__class__.__qualname__}({self.filename()}).up : reading from file")
            with open(self.filename(), 'rt') as fp:
                self.contents = fp.read()
        top.save()

    def is_loaded(self):
        return self.contents is not None

    def clear(self):
        self.contents = None

    def load(self, contents):
        self.contents = contents

    def filename(self):
        return f"{self.name}.{self.extension}"

    def delete(self, name=None):
        use = f"{name or self.name}.{self.extension}"
        os.remove(use)

    def write(self, name=None):
        if self.contents is None:
            raise RuntimeError(f'Cannot write empty contents to file {name or self.name}.{self.extension}')
        use = f"{name or self.name}.{self.extension}"
        with open(use, 'wt') as fp:
            fp.write(self.contents)
            
    def open(self, name=None):
        use = f"{name or self.name}.{self.extension}"
        return open(use, 'rt')

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('name')
        visitor.inline('extension')
        visitor.inline('from_url')
        visitor.offline('contents')
        visitor.endObject(self)

    class Put(resource.Resource):
        """Resource representing a copy of a local file to an instance resource"""
        def __init__(self, name:str=None, extension: str=None, from_url: str|File=None, instance: Peer=None, remote_path:str=None, chmod:str=None, sudo=False):
            self.file = from_url if isinstance(from_url, File) else File(name, extension, from_url)
            self.instance = instance
            self.remote_path = remote_path
            self.chmod = chmod
            self.sudo = sudo
            self.copied = False

        def marshal(self, visitor):
            visitor.beginObject(self)
            visitor.inline('file')
            visitor.inline('instance')
            visitor.inline('remote_path')
            visitor.inline('chmod')
            visitor.inline('sudo')
            visitor.inline('copied')
            visitor.endObject(self)

        def plan(self):
            self.file.plan()

        def up(self, top):
            self.file.up(top)
            if self.copied:
                print(f"{self.__class__.__qualname__}({self.file.name}).up : already copied local file {self.file.filename()} to instance {self.instance.name} remote path {self.remote_path}")
            else:
                print(f"{self.__class__.__qualname__}({self.file.name}).up : copy local file {self.file.filename()} to instance {self.instance.name} remote path {self.remote_path}")
                self.file.write()
                self.instance.put(self.file.filename(), self.remote_path, 60, self.sudo, self.chmod)
                self.copied = True
                top.save()

        def down(self, top):
            if self.copied:
                self.copied = False
                top.save()
