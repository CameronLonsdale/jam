from contextlib import ExitStack

from ..errors import *

from .state import State
from .core import Context, Object, BoundObject, Type
from .function import FunctionType
from .forward import ForwardTarget

class Call(Object):
    called = None
    values = None
    return_type = None
    function = None
    function_type = None

    def __init__(self, called:Object, values:[Object], return_type:Type = None, tokens = None):
        Object.__init__(self, tokens)
        self.called = called
        self.values = values
        self.return_type = return_type

    def verify(self):
        self.called.verify()

        self._stats = self.called.stats

        # Verify arguments and create the function type of the call
        arg_types = []
        for value in self.values:
            value.verify()
            value_type = value.resolveType()

            if value_type is None:
                raise TypeError(message="Cannot pass non value:").add(object=value).add(message="as an argument")
            arg_types.append(value_type)

        self.function_type = FunctionType(arg_types, self.return_type)
        self.function_type.verify()

        # Resolve the call
        with State.type_switch():
            try:
                self.function = self.called.resolveCall(self.function_type)
            except CompilerError as e:
                e.add(object=self, message="").add(object=self.called, message="")
                raise

    def resolveType(self):
        if self.return_type is not None:
            return self.return_type

        # Hack for forward types
        context = self.function.target() if isinstance(self.function, ForwardTarget) else ExitStack()
        with context:
            type = self.function.resolveType().return_type

            if type is not None:
                return type.resolveValue()
            else:
                raise TypeError(object=self.called).add(message="does not have a type")

    def __repr__(self):
        return "{}({})".format(self.called, ", ".join(repr(val) for val in self.values))
