#! env python3

from __future__ import annotations

from typing import List, Dict
import abc

class Resource:
    """Base class for all configurable resources, including lifecycle hooks plan, up, down, order_of_operations"""

    @abc.abstractmethod
    def plan(self):
        """Configure dependencies of this resource on other resuorces"""
        raise RuntimeError('Method plan is not implemented for class '+self.__class__.__qualname__)

    def up(self, top):
        """Make sure all dependent resources are brought up, then bring up this resource.        
        Any resource class must define either up() and down() or order_of_operations()"""
        for operation in self.order_of_operations():
            operation.up(top)
            top.save()

    def down(self, top):
        """Bring down this resource, freeing any cloud resources to which it is attached, 
        then bring down any depenent resources. Proceeds in exact reverse order vs. up().
        Any resource class must define either up() and down() or order_of_operations()"""

        backward = list(self.order_of_operations())
        backward.reverse()
        for operation in backward:
            operation.down(top)
            top.save()

    @abc.abstractmethod
    def order_of_operations(self):
        """For a class which is simply an aggregate of dependent and internal resources,
        returns a list giving the order in which dependent and internal resources should
        proceed through the up/down lifecycle.
        Any resource class must define either up() and down() or order_of_operations()"""

        raise RuntimeError('Method order_of_operations is not implemented for class '+self.__class__.__qualname__)

    @abc.abstractmethod
    def marshal(self, visitor):
        """Pemits visitor to introspect the internal structure of this object, e.g. for the
        purpose of persisting the state of this resource to/from JSON or other format"""
        raise RuntimeError('Method marshal is not implemented for class '+self.__class__.__qualname__)

class Instance:
    @abc.abstractmethod
    def execute(self, args: List[str], timeout: float, stdin=None, cwd=None):
        """Execute a shell command on this instance"""
        raise RuntimeError('Method marshal is not implemented for class '+self.__class__.__qualname__)
