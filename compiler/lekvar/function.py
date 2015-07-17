from ..errors import *

from .state import State
from .core import Context, Object, BoundObject, Type
from .util import checkCompatibility
from .variable import Variable
from .dependent import DependentObject

# Python Predefines
FunctionType = None


class Function(BoundObject):
    _local_context = None
    closed_context = None

    arguments = None
    instructions = None

    type = None
    dependent = False
    verified = False
    static = False

    def __init__(self, name:str, arguments:[Variable], instructions:[Object], return_type:Type = None, tokens = None):
        super().__init__(name, tokens)

        self._local_context = Context(self, arguments)
        self.closed_context = Context(self, [])

        self.arguments = arguments
        self.instructions = instructions

        for arg in self.arguments:
            if arg.type is None:
                arg.type = DependentObject()
                self.dependent = True

        self.type = FunctionType(name, [arg.type for arg in arguments], return_type)

    @property
    def local_context(self):
        return self._local_context

    def copy(self):
        fn = Function(self.name, list(map(copy, self.arguments)), list(map(copy, self.instructions)), self.type.return_type)
        fn.static = self.static
        return fn

    def verify(self):
        if self.verified: return
        self.verified = True

        # Arguments are considered to be already assigned
        for variable in self.arguments:
            variable.resolveAssignment()

        with State.scoped(self, analys = True):
            self.type.verify()

            for instruction in self.instructions:
                instruction.verify()

            # Analytical verification
            self.verifySelf()

    # Used to perform analytical verification after standard verification
    # Guaranteed to run within the scope of the function
    def verifySelf(self):
        # If we have a return type, we must return on all code paths
        if self.type.return_type is not None and not State.soft_scope_state.definately_returns:
            raise SemanticError("All code paths must return", self.tokens)

    def resolveType(self):
        return self.type

    def resolveCall(self, call:FunctionType):
        if not checkCompatibility(self.resolveType(), call):
            raise TypeError("Function is not callable with {}".format(call), self.tokens)

        # Resolve dependencies for dependent arguments
        if self.dependent:
            for index, arg in enumerate(self.arguments):
                if isinstance(arg.type, DependentObject):
                    arg.type.resolveDependency(call.arguments[index])

        return self

    def __repr__(self):
        return "def {}({}) -> {}".format(self.name,
            (", ".join(str(arg) for arg in self.arguments)), self.type.return_type)

class FunctionType(Type):
    arguments = None
    return_type = None

    verified = False

    def __init__(self, name:str, arguments:[Type], return_type:Type = None, tokens = None):
        super().__init__(name, tokens)
        self.arguments = arguments
        self.return_type = return_type

    def copy(self):
        return FunctionType(self.name, list(map(copy, self.arguments)), copy(self.return_type))

    def verify(self):
        if self.verified: return
        self.verified = True

        for arg in self.arguments:
            arg.verify()
        if self.return_type is not None:
            self.return_type.verify()

    def resolveType(self):
        raise InternalError("Not Implemented")

    @property
    def local_context(self):
        raise InternalError("Not Implemented")

    def checkCompatibility(self, other:Type):
        other = other.resolveValue()

        if isinstance(other, FunctionType):
            if len(self.arguments) != len(other.arguments):
                return False

            for self_arg, other_arg in zip(self.arguments, other.arguments):
                if not self_arg.checkCompatibility(other_arg):
                    return False

            # Only check for return type compatibility when the other has one
            if other.return_type is not None:
                return self.return_type.checkCompatibility(other.return_type)
            return True
        return False

    def __repr__(self):
        return "({}) -> {}".format(", ".join(repr(arg) for arg in self.arguments), self.return_type)

#
# Return
#
# Returns can only exist as instructions for functions. They cause the function
# to return with a specified value.

class Return(Object):
    value = None
    function = None

    def __init__(self, value:Object = None, tokens = None):
        super().__init__(tokens)
        self.value = value

    def copy(self):
        return Return(copy(self.value))

    def verify(self):
        scope = State.soft_scope_state.scope
        self.value.verify()
        if hasattr(scope, "bound_context"):
            assert scope.bound_context.scope is State.soft_scope_state.scope.bound_context.scope

        if not isinstance(State.scope, Function):
            raise SyntaxError("Cannot return outside of a function", self.tokens)
        self.function = State.scope

        # Infer function types
        if self.function.type.return_type is None:
            self.function.type.return_type = self.value.resolveType()
        else:
            checkCompatibility(self.function.type.return_type, self.value.resolveType())

        # Update scope state
        State.soft_scope_state.definately_returns = True
        State.soft_scope_state.maybe_returns = True

    def resolveType(self):
        return None

    def __repr__(self):
        return "return {}".format(self.value)
