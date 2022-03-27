import abc
import typing

PayloadType = typing.TypeVar('PayloadType')

class HasPath:
    @abc.abstractmethod
    def path(self) -> typing.List[str]:
        raise RuntimeError(f"Unsupported method")

class Var(typing.Generic[PayloadType]):
    _parent: typing.Union[HasPath, None]
    _name: typing.Union[str, None]
    _default: typing.Union[PayloadType, None]
    _selected: typing.Union[PayloadType, None]
    _options: typing.List[PayloadType]

    def __init__(self, parent: typing.Union[HasPath, None], name: typing.Union[str, None], default: typing.Union[PayloadType,None]=None, *options: PayloadType):
        self._parent = parent
        self._name = name
        self._default = default
        self._selected = None
        self._options = list(options)

    def path(self) -> typing.List[str]:
        if self._name is None:
            raise RuntimeError('name has not been set so path is not yet determined')

        terms: typing.List[str] = []
        if self._parent is not None:
            parent_path = self._parent.path()
            terms += parent_path
        terms += [ self._name ]
        return terms

    def proto(self):
        return f"VAR {'.'.join(self.path())}"

    def __str__(self):
        value = '?' if self._selected is None else str(self._selected)

        return f"{self._name} = {value}"

    def __bool__(self):
        return self._selected is not None
                
    def configure(self):
        if not self._selected and self._default is not None:
            print(f"DEFAULT {self.proto()} := {self._default}")
            self._selected = self._default
        return bool(self)

    def __call__(self) -> PayloadType:
        if self._selected is None:
            if self._default is None:
                raise RuntimeError(f"Configuration var read before a value has been selected {self.proto()}")
            self._selected = self._default
        return self._selected

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('_name')
        visitor.inline('_default')
        visitor.inline('_selected')
        visitor.inline('_options')
        visitor.endObject(self)

    def clear(self):
        self._selected = None
        return self

    def select(self, value: PayloadType):
        self._selected = value
        return self

def Const(literal: PayloadType) -> Var[PayloadType]:
    return Var(None, str(literal), literal).select(literal)

