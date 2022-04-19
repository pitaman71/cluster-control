from __future__ import annotations

import abc
import typing
from . import resource

class Verb:
    @abc.abstractmethod
    def get_names(self) -> typing.List[str]:
        raise RuntimeError('Unsupported method in base class')

    @abc.abstractmethod
    def clone(self) -> Verb:
        raise RuntimeError('Unsupported method in base class')

    @abc.abstractmethod
    def __call__(self, phase: resource.Phase) -> typing.Any:
        raise RuntimeError('Unsupported method in base class')

ResourceType = typing.TypeVar('ResourceType', bound=resource.Resource)

class Do(Verb, typing.Generic[ResourceType]):
    def __init__(
        self, 
        names: typing.List[str],
        exec: typing.Callable[ [ResourceType, resource.Phase], typing.Any]
    ):
        self.names = names
        self.exec = exec

    def get_names(self) -> typing.List[str]:
        return list(self.names)

    @abc.abstractmethod
    def clone(self) -> Verb:
        return Do(self.names, self.exec)

    @abc.abstractmethod
    def __call__(self, resource: ResourceType, phase: resource.Phase) -> typing.Any:
        return self.exec(resource, phase)
