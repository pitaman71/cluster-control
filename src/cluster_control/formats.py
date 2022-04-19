#! env python3

from __future__ import annotations

from typing import Any, List, Dict

import json
from xmlrpc.client import boolean

class JSONSetEncoder(json.JSONEncoder):
    def default(self,  obj):
        if type(obj) is set:
            return dict(_set_object=list(obj))
        elif type(obj) is bytes:
            return dict(_bytes_object=obj.decode('utf-8'))
        else:
            return json.JSONEncoder.default(self, obj)

def json_as_python_set(dct):
    """Decode json {'_set_object': [1,2,3]} to set([1,2,3])

    Example
    -------
    decoded = json.loads(encoded, object_hook=json_as_python_set)

    Also see :class:`JSONSetEncoder`

    """
    if '_set_object' in dct:
        return set(dct['_set_object'])
    elif '_bytes_object' in dct:
        return dct['_bytes_object'].encode('utf-8')
    return dct

def lookup_class(module, suffix, prefix=[]):
    if len(suffix) == 0:
        return module
    if not hasattr(module, suffix[0]):
        raise RuntimeError(f"In module {'.'.join(prefix)} cannot locate definition for class {'.'.join(suffix)}\nValid class names are: {module.__dict__.keys()}")
    return lookup_class(getattr(module, suffix[0]), suffix[1:], prefix + [ suffix[0] ])

class JSONReader:
    """Reads in-memory representation from semi-self-describing JSON by introspecting objects using their marshal method"""
    def __init__(self, modules, json, refs=None):
        self.modules = modules
        self.json = json
        self.obj = None
        self.refs = refs if refs is not None else dict()
        self.is_ref = False

    def beginObject(self, obj):
        """Must be called at the start of any marshal method. Tells this object that we are visiting the body of that object next"""
        if self.obj is None:
            self.obj = obj
        if '__class__' not in self.json:
            raise RuntimeError(f'Expected __class__ to be present in JSON. Properties included {self.json.keys()}')
        class_name = self.json['__class__']
        if class_name not in self.refs:
            self.refs[class_name] = {}            
        by_id = self.refs[class_name]
        if '__id__' in self.json:
            if self.json['__id__'] in by_id:
                #print(f"DEBUG: JSONReader referencing {class_name}#{self.json['__id__']}")
                self.obj = by_id[self.json['__id__']]
                self.is_ref = True
            else:
                #print(f"DEBUG: JSONReader reading {class_name}#{self.json['__id__']}")
                by_id[self.json['__id__']] = self.obj

    def endObject(self, obj):
        """Must be called at the end of any marshal method. Tells this object that we are done visiting the body of that object"""
        pass

    def inline(self, attr_name):
        """For the in-memory object currently being read from JSON, read the value of attribute :attr_name from JSON propery attr_name.
        Expect that the attribute value is probably not a reference to a shared object (though it may be)
        """
        if self.json is None:
            raise RuntimeError('No JSON here')
        elif attr_name in self.json:
            setattr(self.obj, attr_name, JSONReader(self.modules, self.json[attr_name], self.refs).read(getattr(self.obj, attr_name)))
        elif not self.is_ref:
            print(f"WARNING: While reading object of type {self.obj.__class__.__qualname__} property {attr_name} is missing in JSON {json.dumps(self.json)[:80]}")

    def offline(self, attr_name):
        """For the in-memory object currently being read from JSON, read the value of attribute :attr_name from JSON propery attr_name
        Expect that the attribute value is probably a reference to a shared object (though it may not be)
        """
        if self.json is None:
            raise RuntimeError('No JSON here')
        elif attr_name in self.json:
            setattr(self.obj, attr_name, JSONReader(self.modules, self.json[attr_name], self.refs).read(getattr(self.obj, attr_name)))
        elif not self.is_ref:
            print (f"WARNING: While reading object of type {self.obj.__class__.__qualname__} property {attr_name} is missing in JSON {self.json}")

    def instantiate(self, path):
        klass = lookup_class(self.modules, path)
        obj = klass()
        return obj
    
    def read(self, obj=None):
        if isinstance(self.json, list):
            self.obj = [ JSONReader(self.modules, item, self.refs).read() for item in self.json ]
        elif isinstance(self.json, tuple):
            self.obj = (( JSONReader(self.modules, item, self.refs).read() for item in self.json ))
        elif isinstance(self.json, dict):
            if obj is not None:
                self.obj = obj
                self.obj.marshal(self)
            elif '__class__' in self.json:
                self.obj = self.instantiate(self.json['__class__'].split('.'))
                self.obj.marshal(self)
            else:
                self.obj = dict((( (key, JSONReader(self.modules, value, self.refs).read()) for key, value in self.json.items())))
        else:
            self.obj = self.json
        return self.obj

class JSONWriter:
    """Write in-memory representation to semi-self-describing JSON by introspecting objects using their marshal method"""
    obj: Any
    json: Any
    is_ref: boolean
    refs: Any

    def __init__(self, modules, obj, refs=None):
        self.modules = modules
        self.obj = obj
        self.json = None
        self.is_ref = False
        self.refs = refs if refs is not None else dict()

    def beginObject(self, obj):
        """Must be called at the start of any marshal method. Tells this object that we are visiting the body of that object next"""
        self.json = {}
        
        path = [*obj.__class__.__module__.split('.'), *obj.__class__.__qualname__.split('.')]
        class_name = '.'.join(path[1:])
        if class_name not in self.refs:
            self.refs[class_name] = {}
        self.json['__class__'] = class_name
        if id(obj) in self.refs[class_name]:
            self.is_ref = True
        else:            
            ident = str(len(self.refs[class_name]))
            self.refs[class_name][id(obj)] = ident
        self.json['__id__'] = self.refs[class_name][id(obj)]

    def endObject(self, obj):
        """Must be called at the end of any marshal method. Tells this object that we are done visiting the body of that object"""
        pass

    def inline(self, attr_name):
        """For the in-memory object currently being written to JSON, write the value of attribute :attr_name to JSON propery attr_name.
        Expect that the attribute value is probably not a reference to a shared object (though it may be)
        """
        if not (self.is_ref):
            self.json[attr_name] = JSONWriter(self.modules, getattr(self.obj, attr_name), self.refs).toJSON()

    def offline(self, attr_name):
        """For the in-memory object currently being written to JSON, write the value of attribute :attr_name to JSON propery attr_name
        Expect that the attribute value is probably a reference to a shared object (though it may not be)
        """
        if not (self.is_ref):
            self.json[attr_name] = JSONWriter(self.modules, getattr(self.obj, attr_name), self.refs).toJSON()

    def toJSON(self):
        if self.json is not None:
            pass
        elif isinstance(self.obj, list):
            self.json = [ JSONWriter(self.modules, item, self.refs).toJSON() for item in self.obj ]
        elif isinstance(self.obj, tuple):
            self.json = (( JSONWriter(self.modules, item, self.refs).toJSON() for item in self.obj ))
        elif isinstance(self.obj, dict):
            self.json = dict((( (key, JSONWriter(self.modules, value, self.refs).toJSON()) for key, value in self.obj.items())))
        elif hasattr(self.obj, 'marshal'):
            self.obj.marshal(self)
        else:
            self.json = self.obj
        return self.json

    def toString(self):
        return json.dumps(self.toJSON(), indent=4, cls=JSONSetEncoder)
