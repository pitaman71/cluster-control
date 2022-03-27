#! env python3

from __future__ import annotations
from re import I

import typing
import abc

import os
from urllib import request

from . import configurable
from . import resource

class Instance:
    @abc.abstractmethod
    def path(self) -> str:
        raise RuntimeError(f'Method is not implemented in class {self.__class__.__qualname__}')

    @abc.abstractmethod
    def get(self, remote: RemoteFile, dest: Image, timeout: int):
        raise RuntimeError(f'Method is not implemented in class {self.__class__.__qualname__}')
 
    @abc.abstractmethod
    def put(self, src: Image, remote: RemoteFile, timeout:int):
        raise RuntimeError(f'Method is not implemented in class {self.__class__.__qualname__}')

    @abc.abstractmethod
    def delete(self, remote_path: RemoteFile, timeout: int):
        raise RuntimeError(f'Method is not implemented in class {self.__class__.__qualname__}')

class WebResource(resource.Resource):
    url: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.url = configurable.Var(self, 'url')

class LocalFile(resource.Resource):
    local_path: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.local_path = configurable.Var(self, 'local_path')

    def Delete(self):
        if not self.local_path:
            print(f"{self} : local_path is not selected")
        else:
            print(f"{self} : deleting local file {self.local_path}")
            os.remove(self.local_path())

class RemoteFile(resource.Resource):
    remote_path: configurable.Var[str]
    instance: configurable.Var[Instance]
    sudo: configurable.Var[bool]
    mode: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.remote_path = configurable.Var(self, 'remote_path')
        self.instance = configurable.Var(self, 'instance')
        self.sudo = configurable.Var(self, 'sudo', False)
        self.mode = configurable.Var(self, 'mode')

class Transfer(resource.Resource):
    local: resource.Ref[LocalFile]
    remote: resource.Ref[RemoteFile]
    image: resource.Ref[Image]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.local = resource.Ref(self, 'local')
        self.remote = resource.Ref(self, 'remote')
        self.image = resource.Ref(self, 'image', Image)

    def elaborate(self, phase: resource.Phase):
        if not self.remote.elaborate(phase):
            phase.missing(self.remote)
        if not self.image.elaborate(phase):
            phase.missing(self.remote)

    def put(self):
        if not self.remote:
            print(f"{self} : image, remote must be provided {'image' if not self.image else ''} {'remote' if not self.remote else ''}")
        else:
            instance = self.remote().instance()
            if self.local:
                self.image().GetFromLocal(self.local())
            instance.put(self.image(), self.remote(), 60)

    def get(self):
        if not self.remote:
            print(f"{self} : image, remote must be provided {'image' if not self.image else ''} {'remote' if not self.remote else ''}")
        else:
            instance = self.remote().instance()
            instance.get(self.remote(), self.image(), 60)
            if self.local:
                self.image().PutToLocal(self.local())

    def delete(self):
        if not self.remote:
            print(f"{self} : image, remote must be provided {'image' if not self.image else ''} {'remote' if not self.remote else ''}")
        else:
            instance = self.remote().instance()
            instance.delete(self.remote(), 60)

class Image(resource.Resource):
    """In-memory copy of file or web resource"""
    contents: configurable.Var[bytes]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.contents = configurable.Var(self, 'contents')

    def clear(self):
        self.contents.clear()
        
    def load(self, contents: str|bytes):
        if type(contents) is str:
            self.contents.select(contents.encode('utf-8'))
        elif type(contents) is bytes:
            self.contents.select(contents)
        return self

    def as_string(self):
        return self.contents().decode('utf-8')

    def as_bytes(self):
        return self.contents()

    def GetFromWeb(self, web_resource: WebResource):
        if self.contents:
            print(f"{self} : contents are already loaded")
        elif not web_resource.url:
            print(f"{self} : WebResource has no URL selected")
        else:
            with request.urlopen(web_resource.url()) as fp:
                self.contents.select(fp.read())            

    def GetFromLocal(self, local_file: LocalFile):
        if self.contents:
            print(f"{self} : contents are already loaded")
        elif not local_file.local_path:
            print(f"{self} : LocalFile has no URL selected")
        elif not os.path.exists(local_file.local_path()):
            print(f"{self} : Local path {local_file.local_path()} does not exist")
        else:
            print(f"{self} : Reading {self.name} from {local_file.local_path()}")
            with open(local_file.local_path(), 'rb') as fp:
                self.contents.select(fp.read())
        
    def GetFromRemote(self, remote_file: RemoteFile):
        if self.contents:
            print(f"{self} : contents are already loaded")
        elif not remote_file.instance:
            print(f"{self} : RemoteFile has no instance selected")
        elif not remote_file.remote_path:
            print(f"{self} : RemoteFile has no URL selected")
        elif not os.path.exists(remote_file.remote_path()):
            print(f"{self} : RemotePath {remote_file} does not exist")
        else:
            print(f"{self} : Reading {self.name} from {remote_file}")
            remote_file.instance().get(remote_file, self, 60)

    def PutToLocal(self, local_file:LocalFile, overwrite:bool = False):
        if self.contents:
            raise RuntimeError(f'Cannot put empty contents')
        elif not local_file.local_path:
            print(f"{self} : LocalFile has no URL selected")
        elif os.path.exists(local_file.local_path()) and not overwrite:
            print(f"{self} : {local_file.local_path()} does not exist")
        else:
            print(f"{self} : Reading {self.name} from {local_file.local_path()}")
            with open(local_file.local_path(), 'wb') as fp:
                fp.write(self.contents())
            os.chmod(local_file.local_path(), 0o600)

    def Clear(self):
        self.contents.clear()
            
    # def open(self, name=None):
    #     use = f"{name or self.name}.{self.extension}"
    #     return open(use, 'rt')

    def PutToRemote(self, remote_file:RemoteFile):
        if self.contents:
            raise RuntimeError(f'Cannot put empty contents')
        elif not remote_file.instance:
            print(f"{self}.PutToRemote : to remote file has no instance configured {remote_file}")
        elif not remote_file.remote_path:
            print(f"{self}.PutToRemote : to remote file has no remote path configured {remote_file}")
        else:
            print(f"{self}.PutToRemote : copy local image {self.path()} to remote file {remote_file}")
        remote_file.instance().put(self, remote_file, 60)

