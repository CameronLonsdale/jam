import logging
from contextlib import contextmanager
from abc import abstractmethod as abstract, ABC, abstractproperty

from ..errors import *

# Python predefines
# Because most function arguments are declared with types before those types
# are defined, we just set them to null here. This makes the type declaration
# purely syntactic
Context = None
Object = None
BoundObject = None
Type = None
Variable = None
Module = None
Function = None
FunctionType = None
Method = None

#
# Infrastructure
#

def verify(module:Module, builtin:Module, logger = logging.getLogger()):
    # Set up the initial state before verifying
    State.init()
    State.builtins = builtin
    State.logger = logger.getChild("lekvar")

    State.logger.info(module)

    module.verify()

# Resolves a reference inside of a given scope.
def resolveReference(reference:str):
    found = []

    # Collect all objects with a name matching reference up the tree of scopes
    scope = State.scope
    while True:
        context = scope.local_context

        if context is not None and reference in context:
            found.append(context[reference])

        # Go to builtins once the top of the tree is reached, otherwise move up
        if scope is State.builtins:
            break
        else:
            scope = scope.bound_context.scope if (scope.bound_context is not None) else State.builtins

    # Only a single found object is valid
    if len(found) < 1:
        raise MissingReferenceError("No reference to {}".format(reference))
    elif len(found) > 1:
        raise AmbiguityError("Ambiguous reference to {}".format(reference))

    return found[0]

# More general copy function which handles None
def copy(obj):
    return obj.copy() if obj else None

# The global state for the verifier
class State:
    builtins = None
    logger = None
    scope = None
    soft_scope_stack = None

    @classmethod
    def init(cls):
        cls.builtins = None
        cls.logger = None
        cls.scope = None
        cls.soft_scope_stack = None

    @classmethod
    @contextmanager
    def scoped(cls, scope:BoundObject):
        previous = cls.scope, cls.soft_scope_stack
        cls.scope = scope
        cls.soft_scope_stack = []
        yield
        cls.scope, cls.soft_scope_stack = previous

    @classmethod
    @contextmanager
    def softScoped(cls, scope:Object):
        cls.soft_scope_stack.append(scope)
        yield
        cls.soft_scope_stack.pop()

#
# Abstract Base Structures
#
# These structures form the basis of Lekvar. They provide the base functionality
# needed to implement higher level features.

class Context:
    scope = None
    children = None

    def __init__(self, scope:BoundObject, children:[BoundObject]):
        self.scope = scope

        self.children = {}
        for child in children:
            self.addChild(child)

    def copy(self):
        return list(map(copy, self.children.values()))

    def verify(self):
        for child in self.children.values():
            child.verify()

    # Doubly link a child to the context
    def addChild(self, child):
        self.children[child.name] = child
        self.fakeChild(child)

    # Bind the child to the context, but not the context to the child
    # Useful for setting up "parenting" for internal objects
    def fakeChild(self, child):
        child.bound_context = self

    def __contains__(self, name:str):
        return name in self.children

    def __getitem__(self, name:str):
        return self.children[name]

    def __setitem__(self, name:str, value:BoundObject):
        self.children[name] = value

    def __iter__(self):
        return iter(self.children.values())

    def __add__(self, other:Context):
        for child in self.children.values():
            if child.name in other.children:
                raise AmbiguityError()

        return Context(None, self.children.values() + other.children.values())

    def __repr__(self):
        return "{}<{}>".format(self.__class__.__name__, ", ".join(map(str, self.children.values())))

class Object(ABC):
    tokens = None

    def __init__(self, tokens = None):
        self.tokens = tokens

    # Should return a unverified deep copy of the object
    @abstract
    def copy(self):
        pass

    # The main verification function. Should raise a CompilerError on failure
    @abstract
    def verify(self):
        pass

    # Should return an instance of Type representing the type of the object
    # Returns None for instructions
    @abstract
    def resolveType(self) -> Context:
        pass

    # Should either return None or a context accessible from the global scope
    @property
    def global_context(self) -> Context:
        return None

    # Should either return None or a context accessibly from the local scope
    @property
    def local_context(self):
        return None

    # Should return a function object that matches a function signature
    def resolveCall(self, call:FunctionType) -> Function:
        raise TypeError("{} object is not callable".format(self))

    # Resolves an attribute
    # final
    def resolveAttribute(self, reference:str):
        self = self.resolveValue()
        instance_context = self.resolveType().instance_context

        if instance_context is not None:
            if self.global_context is not None:
                context = instance_context + self.global_context
            else:
                context = instance_context
        else:
            context = self.global_context

        if context is not None and reference in context:
            return context[reference]
        raise MissingReferenceError("{} does not have an attribute {}".format(self, reference))

    def resolveValue(self):
        return self

    def __repr__(self):
        return "{}".format(self.__class__.__name__)

class BoundObject(Object):
    name = None
    bound_context = None
    static = False
    dependent = False

    def __init__(self, name, tokens = None):
        super().__init__(tokens)
        self.name = name

    def __repr__(self):
        return "{}({})".format(self.__class__.__name__, self.name)

class Type(BoundObject):
    @property
    def instance_context(self):
        None

    @abstract
    def checkCompatibility(self, other:Type) -> bool:
        pass

#
# Module
#
# A module represents a simple namespace container scope.

class Module(BoundObject):
    context = None
    main = None
    verified = False
    static = True

    def __init__(self, name:str, children:[BoundObject], main:Function = None, tokens = None):
        super().__init__(name, tokens)

        self.context = Context(self, children)
        for child in children:
            child.static = True

        self.main = main
        self.context.fakeChild(self.main)

    def copy(self):
        return Module(self.name, copy(self.context))

    def verify(self):
        if self.verified: return
        self.verified = True

        with State.scoped(self):
            self.main.verify()
            self.context.verify()

    def resolveType(self):
        return ModuleType(self)

    @property
    def local_context(self):
        return self.context

    @property
    def global_context(self):
        return self.context

    def __repr__(self):
        return "module {}".format(self.name)

class ModuleType(Type):
    module = None

    def __init__(self, module:Module, tokens = None):
        super().__init__(tokens)
        self.module = module

    def copy(self):
        return ModuleType(copy(self.module))

    def verify(self):
        self.module.verify()

    def resolveType(self):
        raise InternalError("Not Implemented")

    def checkCompatibility(self, other:Type):
        return other.module is self.module

#
# Dependent Type
#
# A Dependent type acts as an interface for types. When a variable has a
# dependent type and is called, it's dependent type changes to reflect the call.
# This means that dependent types can be used to implement generics.

class DependentType(Type):
    compatibles = None
    target = None

    def __init__(self, compatibles:[Type] = None, tokens = None):
        super().__init__("", tokens)

        if compatibles is None: compatibles = []
        self.compatibles = compatibles

    def copy(self):
        return DependentType(self.compatibles[:])

    def verify(self):
        pass

    def checkCompatibility(self, other:Type):
        # If dependent type is targeted, only check for the target type
        if self.target is not None:
            return self.target.checkCompatibility(other)

        # Check with all compatible types
        #for type in self.compatibles:
        #    if not type.checkCompatibility(other):
        #        return False

        if other not in self.compatibles:
            self.compatibles.append(other)

        return True

    def resolveType(self):
        raise InternalError("Not Implemented")

    def __repr__(self):
        if self.target is None:
            return "{}<{}>".format(self.__class__.__name__, self.compatibles)
        else:
            return "{} as {}".format(self.__class__.__name__, self.target)

#
# Function
#
# Functions are a basic container for instructions.

class Function(BoundObject):
    _local_context = None
    closed_context = None

    arguments = None
    instructions = None

    type = None
    dependent = False
    verified = False

    def __init__(self, name:str, arguments:[Variable], instructions:[Object], return_type:Type = None, tokens = None, static = False):
        super().__init__(name, tokens)
        self._bound_context = None

        self.static = static
        if not static:
            self._local_context = Context(self, arguments)
        self.closed_context = Context(self, [])

        self.arguments = arguments
        self.instructions = instructions

        for arg in self.arguments:
            if arg.type is None:
                arg.type = DependentType()
                self.dependent = True

        self.type = FunctionType(name, [arg.type for arg in arguments], return_type)

    @property
    def local_context(self):
        if self.static:
            return self._bound_context
        return self._local_context

    @property
    def bound_context(self):
        if self.static:
            return self._bound_context.scope.bound_context
        return self._bound_context

    @bound_context.setter
    def bound_context(self, value):
        self._bound_context = value

    def copy(self):
        fn = Function(self.name, list(map(copy, self.arguments)), list(map(copy, self.instructions)), self.type.return_type)
        fn.static = self.static
        return fn

    def verify(self):
        if self.verified: return
        self.verified = True

        with State.scoped(self):
            self.type.verify()

            for instruction in self.instructions:
                instruction.verify()

            # Further, analytical verification
            self.verifySelf()

    def verifySelf(self):
        # Ensure non-void functions return
        if not any(isinstance(inst, Return) for inst in self.instructions) and self.type.return_type is not None:
            raise SemanticError("All code paths must return")

    def resolveType(self):
        return self.type

    def resolveCall(self, call:FunctionType):
        if not self.resolveType().checkCompatibility(call):
            raise TypeError("{} is not compatible with {}".format(call, self.resolveType()))

        if not self.dependent:
            return self

        # Create a template instance
        fn = copy(self)
        for index, arg in enumerate(fn.arguments):
            if isinstance(arg.type, DependentType):
                fn.type.arguments[index] = arg.type.target = call.arguments[index]
        fn.verify()
        return fn

    def __repr__(self):
        return "def {}({}) -> {}".format(self.name,
            (", ".join(str(arg) for arg in self.arguments)), self.type.return_type)

class ExternalFunction(BoundObject):
    external_name = None
    type = None

    dependent = False
    verified = False

    def __init__(self, name:str, external_name:str, arguments:[Type], return_type:Type, tokens = None):
        super().__init__(name, tokens)
        self.external_name = external_name
        self.type = FunctionType(external_name, arguments, return_type)

    def copy(self):
        raise InternalError("Not Implemented")

    def verify(self):
        if self.verified: return
        self.verified = True

        with State.scoped(self):
            self.type.verify()

    def resolveType(self):
        return self.type

    resolveCall = Function.resolveCall

    def __repr__(self):
        return "def {}=>{} -> {}".format(self.name, self.external_name, self.type)

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

        with State.scoped(self):
            for arg in self.arguments:
                arg.verify()
            if self.return_type is not None:
                self.return_type.verify()

    def resolveType(self):
        raise InternalError("Not Implemented")

    def checkCompatibility(self, other:Type, reversed=False):
        other = other.resolveValue()

        if isinstance(other, FunctionType):
            if len(self.arguments) != len(other.arguments):
                return False

            for self_arg, other_arg in zip(self.arguments, other.arguments):
                if not self_arg.checkCompatibility(other_arg):
                    return other_arg.checkCompatibility(self_arg)

            return True
        return other.checkCompatibility(self)

    def __repr__(self):
        return "({}) -> {}".format(", ".join(repr(arg) for arg in self.arguments), self.return_type)

#
# Method
#
# A method is a generic container for functions. It implements the functionality
# for function overloading.

class Method(BoundObject):
    overload_context = None
    verified = False

    def __init__(self, name:str, overloads:[Function], tokens = None):
        super().__init__(name, tokens)

        self.overload_context = Context(self, [])
        for overload in overloads:
            self.addOverload(overload)

    def copy(self):
        return Method(self.name, list(map(copy, self.overload_context.children.values())))

    def addOverload(self, overload:Function):
        overload.name = str(len(self.overload_context.children))
        self.overload_context.addChild(overload)

    def assimilate(self, other:Method):
        for overload in other.overload_context:
            self.addOverload(overload)

    def verify(self):
        if self.verified: return
        self.verified = True

        with State.scoped(self):
            for overload in self.overload_context:
                overload.verify()

    def resolveType(self):
        return MethodType(self.name, [fn.resolveType() for fn in self.overload])

    def resolveCall(self, call:FunctionType):
        matches = []

        # Collect overloads which match the call type
        for overload in self.overload_context:
            try:
                matches.append(overload.resolveCall(call))
            except TypeError:
                continue

        # Allow only one match
        if len(matches) < 1:
            raise TypeError("{} is not compatible with {}".format(call, self))
        elif len(matches) > 1 and not State.scope.dependent:
            raise TypeError("Ambiguous overloads: {}".format(matches))

        return matches[0]

    def __repr__(self):
        return "method {}".format(self.name)

class MethodType(Type):
    overloads = None

    def __init__(self, name:str, overloads:[FunctionType], tokens = None):
        super().__init__(name, tokens)
        self.overloads = overloads

#
# Class
#
# A class provides a generic interface for creating user types.

class Class(Type):
    constructor = None
    instance_context = None

    verified = False

    def __init__(self, name:str, constructor:Method, attributes:[BoundObject], tokens = None):
        super().__init__(name, tokens)

        self.instance_context = Context(self, attributes)

        # Convert constructor method of functions to method of constructors
        #TODO: Eliminate the need for this
        if constructor is not None:
            self.constructor = constructor
            for overload in self.constructor.overload_context:
                name = overload.name
                self.constructor.overload_context[name] = Constructor(overload, self)
                self.constructor.overload_context[name].bound_context = self.constructor.overload_context
                self.constructor.overload_context[name].closed_context.addChild(Variable("self", self))
            self.instance_context.fakeChild(self.constructor)

        for child in self.instance_context:
            if isinstance(child, Method):
                for overload in child.overload_context:
                    overload.closed_context.addChild(Variable("self", self))

    def copy(self):
        return Class(self.name, copy(self.constructor), list(map(copy, self.constructor.overload_context.children.values())))

    def verify(self):
        if self.verified: return
        self.verified = True

        with State.scoped(self):
            if self.constructor is not None:
                self.constructor.verify()
            self.instance_context.verify()

    def resolveCall(self, call:FunctionType):
        if self.constructor is None:
            raise TypeError("Class {} does not have a constructor".format(self))

        function = self.constructor.resolveCall(call)
        function.type.return_type = self
        return function

    def resolveType(self):
        raise InternalError("Not Implemented")

    @property
    def local_context(self):
        return self.instance_context

    def checkCompatibility(self, other:Type) -> bool:
        return other.resolveValue() is self

    def __repr__(self):
        contents = "\n".join(repr(val) for val in [self.constructor] + list(self.instance_context))
        return "class {}\n{}\nend".format(self.name, contents)

class Constructor(Function):
    def __init__(self, function:Function, constructing:Type, tokens = None):
        super().__init__(function.name, function.arguments, function.instructions, function.type.return_type, tokens)

        if function.type.return_type is not None:
            raise TypeError("Constructors must return nothing")
        function.type.return_type = constructing

    def verifySelf(self):
        for instruction in self.instructions:
            if isinstance(instruction, Return):
                raise SyntaxError("Returns within constructors are invalid")

#
# Loop
#

class Loop(Object):
    function = None
    instructions = None

    def __init__(self, instructions, tokens = None):
        super().__init__(tokens)

        self.instructions = instructions

    def copy(self):
        return Loop(self.instructions)

    def verify(self):
        if not isinstance(State.scope, Function):
            raise SyntaxError("Cannot branch outside method")
        self.function = State.scope

        with State.softScoped(self):
            for instruction in self.instructions:
                instruction.verify()

    def resolveType(self):
        return None

#
# Break
#

class Break(Object):
    loop = None

    def __init__(self, tokens = None):
        super().__init__(tokens)

    def copy(self):
        return Break()

    def verify(self):
        self.loop = self._getSoftScope()
        if self.loop is None:
            raise SyntaxError("Cannot break outside loop")

    def _getSoftScope(self):
        for scope in State.soft_scope_stack:
            if isinstance(scope, Loop):
                return scope
        return None

    def resolveType(self):
        return None

#
# Branch
#

class Branch(Object):
    function = None
    condition = None
    true_instructions = None
    false_instructions = None

    def __init__(self, condition, true_instructions, false_instructions, tokens = None):
        super().__init__(tokens)

        self.condition = condition
        self.true_instructions = true_instructions
        self.false_instructions = false_instructions

    def copy(self):
        return Branch(self.condition, self.true_instructions, self.false_instructions)

    def verify(self):
        if not isinstance(State.scope, Function):
            raise SyntaxError("Cannot branch outside method")
        self.function = State.scope

        self.condition.verify()

        with State.softScoped(self):
            #TODO: Analysis on branch dependent instructions
            for instruction in self.true_instructions:
                instruction.verify()

            for instruction in self.false_instructions:
                instruction.verify()

    def resolveType(self):
        return None

#
# Variable
#
# A variable is a simple container for a value. The scope object may be used
# in conjunction with assignments and values for advanced functionality.

class Variable(BoundObject):
    type = None

    def __init__(self, name:str, type:Type = None, tokens = None):
        super().__init__(name, tokens)
        self.type = type

    def copy(self):
        var = Variable(self.name, copy(self.type))
        var.static = self.static
        return var

    def verify(self):
        if self.type is not None:
            self.type.verify()

    def resolveType(self):
        return self.type

    def __repr__(self):
        return "{}:{}".format(self.name, self.type)

#
# Assignment
#
# Assignment instructions allow for saving values inside of variables.

class Assignment(Object):
    variable = None
    value = None
    scope = None

    def __init__(self, variable:Variable, value:Object, tokens = None):
        super().__init__(tokens)
        self.variable = variable
        self.value = value

    def copy(self):
        return Assignment(copy(self.variable), copy(self.value))

    def verify(self):
        self.scope = State.scope

        # Try resolving the reference. If resolution fails, add a new variable
        # to the scope.
        try:
            variable = resolveReference(self.variable.name)
        except MissingReferenceError:
            State.scope.local_context.addChild(self.variable)
        else:
            # Verify variable type
            if variable.type is None:
                variable.type = self.variable.type
            elif self.variable.type is not None:
                raise TypeError("Cannot override variable type")

            self.variable = variable

        self.value.verify()
        self.variable.verify()

        value_type = self.value.resolveType()
        # Infer or verify the variable type
        if self.variable.type is None:
            self.variable.type = value_type
        elif not value_type.checkCompatibility(self.variable.type):
            raise TypeError("Cannot assign {} of type {} to variable {} of type {}".format(self.value, value_type, self.variable, self.variable.type))

    def resolveType(self):
        return None

    def __repr__(self):
        return "{} = {}".format(self.__class__.__name__, self.variable, self.value)

#
# Call
#
# A call is a simple instruction to execute a given function with specific
# arguments.

class Call(Object):
    called = None
    values = None
    function = None

    def __init__(self, called:Object, values:[Object], tokens = None):
        super().__init__(tokens)
        self.called = called
        self.values = values
        self.function = None

    def copy(self):
        return Call(copy(self.called), list(map(copy, self.values)))

    def verify(self):
        super().verify()

        self.called.verify()

        # Verify arguments and create the function type of the call
        arg_types = []
        for val in self.values:
            val.verify()
            arg_types.append(val.resolveType())
        call_type = FunctionType("", arg_types)

        # Resolve the call
        self.function = self.called.resolveCall(call_type)

    def resolveType(self):
        return self.function.resolveType().return_type

    def __repr__(self):
        return "{}({})".format(self.called, ", ".join(repr(val) for val in self.values))

#
# Literal
#
# A literal is a direct piece of constant data in memory.

class Literal(Object):
    data = None
    type = None

    def __init__(self, data, type:Type, tokens = None):
        super().__init__(tokens)
        self.data = data
        self.type = type

    def copy(self):
        return self

    def verify(self):
        super().verify()

        self.type.verify()

    def resolveType(self):
        return self.type

    def __repr__(self):
        return "{}({})".format(self.type, self.data)

#
# Reference
#
# A reference is a by-name link to a object in the current or parent scopes.
# References are used to prevent object duplication.

class Reference(Type):
    reference = None
    value = None

    verified = False

    def __init__(self, reference:str, tokens = None):
        super().__init__(tokens)
        self.reference = reference

    def copy(self):
        return Reference(self.reference)

    def verify(self):
        if self.verified: return
        self.verified = True

        # Resolve the reference using general reference resolution
        self.value = resolveReference(self.reference)
        self.value.verify()

    def resolveType(self):
        return self.value.resolveType()

    @property
    def local_context(self):
        return self.value.local_context

    @property
    def global_context(self):
        return self.value.global_context

    @property
    def instance_context(self):
        return self.value.instance_context

    def resolveCall(self, call:FunctionType):
        return self.value.resolveCall(call)

    def resolveValue(self):
        return self.value.resolveValue()

    def checkCompatibility(self, other:Type):
        return self.value.checkCompatibility(other)

    def __repr__(self):
        return "{}".format(self.reference)

class Attribute(Type):
    value = None
    reference = None
    attribute = None

    verified = False

    def __init__(self, value:Object, reference:str, tokens = None):
        super().__init__(tokens)
        self.value = value
        self.reference = reference

    def copy(self):
        return Attribute(self.value, self.reference)

    def verify(self):
        if self.verified: return
        self.verified = True

        self.value.verify()
        # Resolve the attribute using the values attribute resolution
        self.attribute = self.value.resolveAttribute(self.reference)

        if self.attribute is None:
            raise MissingReferenceError("{} does not have an attribute {}".format(self.value, self.reference))

    @property
    def local_context(self):
        return self.attribute.local_context

    @property
    def global_context(self):
        return self.attribute.global_context

    @property
    def instance_context(self):
        return self.attribute.instance_context

    def resolveType(self):
        return self.attribute.resolveType()

    def resolveCall(self, call:FunctionType):
        return self.attribute.resolveCall(call)

    def resolveValue(self):
        return self.attribute.resolveValue()

    def checkCompatibility(self, other:Type):
        return self.attribute.checkCompatibility(other)

    def __repr__(self):
        return "{}.{}".format(self.value, self.reference)

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
        self.value.verify()

        if not isinstance(State.scope, Function):
            raise SyntaxError("Cannot return outside of a method")
        self.function = State.scope

        # Infer function types
        if self.function.type.return_type is None:
            self.function.type.return_type = self.value.resolveType()
        else:
            self.function.type.return_type.checkCompatibility(self.value.resolveType())

    def resolveType(self):
        return None

    def __repr__(self):
        return "return {}".format(self.value)

#
# Comment
#
# A comment is a piece of metadata that is generally not compiled

class Comment(Object):
    contents = None

    def __init__(self, contents, tokens = None):
        super().__init__(tokens)
        self.contents = contents

    def copy(self):
        return Comment(self.contents)

    def verify(self):
        pass

    def resolveType(self):
        return None

    def __repr__(self):
        return "# {} #".format(self.contents)
