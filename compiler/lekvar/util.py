import logging
from contextlib import contextmanager

from ..errors import *

from .state import State
from .core import Object, BoundObject, Scope, Type

# Python predefines
Module = None

def checkCompatibility(type1:Type, type2:Type):
    if type1.checkCompatibility(type2):
        return True
    return type2.checkCompatibility(type1)

# Resolves a reference inside of a given scope.
def resolveReference(reference:str, exclude = None):
    # Collect all objects with a name matching reference up the tree of scopes
    found = []

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

    found = [scope for scope in found if scope is not exclude]

    # Only a single found object is valid
    if len(found) < 1:
        raise MissingReferenceError("No reference to {}".format(reference))
    elif len(found) > 1:
        raise AmbiguityError(
            [("Ambiguous reference to {}\nMatches:".format(reference), [])] +
            [("", match.tokens) for match in found]
        )

    return found[0]

# Resolve a attribute of a given object
def resolveAttribute(object:Object, reference:str):
    context = object.context

    if context is not None and reference in context:
        return context[reference]

    raise MissingReferenceError("{} does not have an attribute {}".format(object, reference), object.tokens)

# Check whether a object is within a scope
def inScope(object:BoundObject, scope:Scope):
    while scope is not None:
        if object == scope:
            return True
        scope = scope.bound_context.scope if scope.bound_context else None
    return False
