#! env python3

from __future__ import annotations

import typing
import os
import sys
import abc
import json

from . import configurable
from . import formats
from . import resource

class Persistor:
    file_name: str
    root: Resource

    @abc.abstractmethod
    def save(self, *resources: typing.List[Resource]):
        pass

class PersistInFile(Persistor):
    def __init__(self, file_name: str, root: Resource):
        self.file_name = file_name
        self.root = root

    def save(self, *resources: typing.List[Resource]):
        next_file_name = f"{self.file_name}.next"
        with open(next_file_name, 'wt') as fp:
            writer = formats.JSONWriter(sys.modules[__name__], self.root)
            self.root.marshal(writer)
            fp.write(writer.toString())
        os.rename(next_file_name, self.file_name)

    def load(self):
        if os.path.exists(self.file_name):
            with open(self.file_name, 'rt') as fp:
                as_json = json.load(fp)
                reader = formats.JSONReader(sys.modules[__name__], as_json)
                self.root.marshal(reader)

class Resource(configurable.HasPath):
    """Base class for all configurable resources, including lifecycle hooks plan, up, down, order_of_operations"""
    id: str
    name: typing.Union[ None, str ]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        if resource_path is not None:
            self.name = '.'.join(resource_path)
        else:
            self.name = None
        
    def __str__(self):
        name = f'"{self.name}"' if self.name is not None else '?'
        return f"{self.__class__.__qualname__}:{name}"

    def path(self) -> typing.List[str]:
        return [] if self.name is None else self.name.split('.')

    def proto(self):
        return f"RESOURCE {self.name}"

    def alias(self, **kwargs):
        for key, value in kwargs.items():
            if isinstance(value, configurable.Var):
                self.__dict__[key] = value
            elif isinstance(value, resource.Ref):
                self.__dict__[key].borrow(value)
            elif isinstance(value, resource.Resource):
                self.__dict__[key].own(value)
            else:
                self.__dict__[key] = configurable.Const(value)
        return self

    def marshal(self, visitor: formats.JSONReader|formats.JSONWriter, inner: typing.Callable[[ formats.JSONReader|formats.JSONWriter ], typing.Any ] = lambda visitor: 0 ):
        visitor.beginObject(self)
        visitor.inline('name')
        for key, value in self.__dict__.items():
            if isinstance(value, configurable.Var) or isinstance(value, Ref):
                visitor.inline(key)
        inner(visitor)
        visitor.endObject(self)

    def collect(self, 
        var: typing.Set[configurable.Var],
        resource: typing.Set[Resource],
    ):
        """Configure dependencies of this resource on other resuorces"""
        for key, value in self.__dict__.items():
            if isinstance(value, configurable.Var):
                var.add(value)
            elif isinstance(value, Ref):
                if value._resource is not None:
                    if value._resource not in resource:
                        if not isinstance(value._resource, Resource):
                            raise RuntimeError("type error")
                        resource.add(value._resource)
                        value._resource.collect(var, resource)

    def elaborate(self, phase: Phase):
        """Configure dependencies of this resource on other resuorces"""
        for key, value in self.__dict__.items():
            if isinstance(value, Ref):
                with phase.sub(f"ELABORATE {value}") as phase:
                    if not value.elaborate(phase):
                        phase.missing(value)

    def up(self, phase: Phase):
        """Make sure all dependent resources are brought up, then bring up this resource.        
        Any resource class must define either up() and down() or order_of_operations()"""
        for operation in self.order_of_operations():
            with Phase(f"UP   {operation}", phase.persistor, operation) as phase:
                operation.up(phase)

    def down(self, phase: Phase):
        """Bring down this resource, freeing any cloud resources to which it is attached, 
        then bring down any depenent resources. Proceeds in exact reverse order vs. up().
        Any resource class must define either up() and down() or order_of_operations()"""

        backward = list(self.order_of_operations())
        backward.reverse()
        for operation in backward:
            with Phase(f"DOWN {operation}", phase.persistor, operation) as phase:
                operation.down(phase)

    def order_of_operations(self):
        """For a class which is simply an aggregate of dependent and internal resources,
        returns a list giving the order in which dependent and internal resources should
        proceed through the up/down lifecycle.
        Any resource class must define either up() and down() or order_of_operations()"""

        result: typing.List[Resource] = []
        for key, value in self.__dict__.items():
            if isinstance(value, Ref):
                if value._resource is None:
                    print(f"WARNING: null resource for {value}")
                elif not isinstance(value._resource, Resource):
                    raise RuntimeError(f"TYPE ERROR: expected a Ref but got a {value}")
                else:
                    result.append(value._resource)
        return result

ResourceType = typing.TypeVar('ResourceType', bound=Resource)

class Phase:
    description: str
    persistor: Persistor
    resources: typing.List[Resource]
    has_error: bool

    def __init__(self, description: str, persistor: Persistor, *resources: Resource):
        self.description = description
        self.persistor = persistor
        self.resources = list(resources)
        self.has_error = False

    def __enter__(self):
        print(f"BEGIN {self.description}")
        return self

    def __exit__(self, type, value, traceback):
        print(f"END   {self.description}")
        self.persistor.save(self.resources)
        if self.has_error:
            raise RuntimeError("Missing configuration items")
    
    def sub(self, description):
        return Phase(description, self.persistor, *self.resources)
    
    def missing(self, item):
        print(f"MISSING {item}")
        self.has_error = True
        
class Action(typing.Generic[ResourceType]):
    target: ResourceType
    persistor: Persistor

    def __init__(self, target: ResourceType, persistor: Persistor):
        self.target = target
        self.persistor = persistor

    @abc.abstractmethod
    def __call__(self):
        raise RuntimeError('Method is not implemented for class '+self.__class__.__qualname__)

    def phase(self, description: str) -> Phase:
        if not isinstance(self.target, Resource):
            raise RuntimeError('type error')
        return Phase(description, self.persistor, self.target)

class Instance(Resource):
    @abc.abstractmethod
    def execute(self, args: typing.List[str], timeout: float, stdin=None, cwd=None):
        """Execute a shell command on this instance"""
        raise RuntimeError('Method is not implemented for class '+self.__class__.__qualname__)

class Ref(typing.Generic[ResourceType]):
    _path: typing.List[str]
    _name: str
    _resource: typing.Union[ None, ResourceType ]
    _owner: None|Ref[ResourceType]

    def __init__(self, parent: typing.Union[None, Resource]=None, name: str=''):
        self._path = [] if parent is None else parent.path()
        self._name = name
        self._resource = None
        self._owner = None

    def path(self):
        return [ *self._path, self._name ]
        
    def __str__(self):
        return f"Ref({'.'.join(self.path())})"

    def __bool__(self):
        if self._owner is not None:
            return bool(self._owner)
        return self._resource is not None

    def resolve(self, phase: resource.Phase, generator: typing.Union[None, typing.Callable[ [ typing.List[str] ], ResourceType ]]=None):
        if self._owner is not None:
            pass
        elif self._resource is None and generator is not None:
            self._resource = generator(self.path())
            print(f"CREATE resource {self}")

    def __call__(self) -> ResourceType:
        if self._owner is not None:
            return self._owner()
        if self._resource is None:
            raise RuntimeError(f"Resource reference is not connected {self}")
        return self._resource

    def elaborate(self, phase: resource.Phase):
        self.resolve(phase)
        if self._resource is None:
            print(f"SKIP unresolved resource {self}")
        else:
            self._resource.elaborate(phase)
        return bool(self)

    def borrow(self, owner: Ref[ResourceType]):
        self._owner = owner
        return self

    def own(self, resource: ResourceType):
        self._resource = resource
        return self

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('_path')
        visitor.inline('_name')
        visitor.inline('_resource')
        visitor.inline('_owner')
        visitor.endObject(self)
