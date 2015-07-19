import logging
from io import IOBase

from .. errors import *
from .. import lekvar

from . import import_
from .lexer import Lexer, Tokens

#
# Tools
#

def parseFile(source:IOBase, logger=logging.getLogger()):
    try:
        return Parser(Lexer(source), logger).parseModule(False)
    except CompilerError as e:
        source.seek(0)
        e.format(source.read())
        raise e

#
# Parser
#

BINARY_OPERATIONS = [
    {Tokens.equality, Tokens.inequality,
     Tokens.smaller_than, Tokens.smaller_than_or_equal_to,
     Tokens.greater_than, Tokens.greater_than_or_equal_to},
    {Tokens.addition, Tokens.subtraction},
    {Tokens.multiplication, Tokens.division, Tokens.integer_division},
]

BINARY_OPERATION_TOKENS = {type for operation in BINARY_OPERATIONS for type in operation }

UNARY_OPERATIONS = [
    Tokens.addition,
    Tokens.subtraction,
    Tokens.logical_negation,
]

UNARY_OPERATION_TOKENS = set(UNARY_OPERATIONS)

class Parser:
    lexer = None
    tokens = None
    logger = None

    def __init__(self, lexer, logger):
        self.lexer = lexer
        self.tokens = []
        self.logger = logger.getChild("Parser")

    # Return the next token and move forward by one token
    def next(self):
        if len(self.tokens) == 0:
            return self.lexer.lex()
        else:
            return self.tokens.pop(0)

    # Look ahead of the current token by num tokens
    def lookAhead(self, num = 1):
        while len(self.tokens) < num:
            self.tokens.append(self.lexer.lex())
        return self.tokens[num - 1]

    # Throw an unexpected token error
    def _unexpected(self, token):
        raise SyntaxError("Unexpected {}: `{}`".format(token.type.name, token.data), [token])

    # Strip all tokens of a type, returning one lookAhead or None
    def strip(self, types:[Tokens]):
        token = self.lookAhead()
        if token is None: return None

        while token.type in types:
            self.next()
            token = self.lookAhead()
            if token is None: return None

        return token

    # Parse for an expected token, returning it's data
    # May also pass a tokens argument, to which the lexed token is appended
    def expect(self, type:Tokens, tokens:[] = None):
        token = self.next()

        if token is None:
            raise SyntaxError("Expected {} before EOF".format(type.name))

        if token.type != type:
            self._unexpected(token)

        if tokens is not None:
            tokens.append(token)

        return token

    def addChild(self, children:{str: lekvar.BoundObject}, value:lekvar.BoundObject):
        name = value.name

        if isinstance(value, lekvar.Method):
            if name in children:
                children[name].assimilate(value)
            else:
                children[name] = value
        else:
            children[name] = value

    def parseModule(self, inline = True):
        if inline:
            tokens = [self.next()]
            assert tokens[0].type == Tokens.module_kwd

            module_name = self.expect(Tokens.identifier, tokens).data
        else:
            tokens = []
            module_name = "main"

        children = {}
        instructions = []

        while True:
            # Check for end_kwd
            if inline:
                token = self.lookAhead()
                if token is None:
                    raise SyntaxError("Expected `end` before EOF for module", tokens)
                elif token.type == Tokens.end_kwd:
                    tokens.append(self.next())
                    break

            value = self.parseLine()

            # EOF escape
            if value is None: break

            if isinstance(value, lekvar.BoundObject):
                # Scopes are automatically added as children
                self.addChild(children, value)
            else:
                # Other values are added as instructions
                instructions.append(value)

        return lekvar.Module(module_name, list(children.values()), instructions, tokens)

    def parseLine(self):
        # Parse a line. The line may not exist

        token = self.lookAhead()
        if token is None: return None

        if token.type == Tokens.comment:
            return self.parseComment()
        elif token.type == Tokens.return_kwd:
            return self.parseReturn()
        elif token.type == Tokens.import_kwd:
            return self.parseImport()
        elif token.type == Tokens.if_kwd:
            return self.parseBranch()
        elif token.type == Tokens.while_kwd:
            return self.parseWhile()
        elif token.type == Tokens.loop_kwd:
            return self.parseLoop()
        elif token.type == Tokens.break_kwd:
            return self.parseBreak()
        elif token.type in (Tokens.identifier, Tokens.const_kwd):
            # The assignment operator must be within the first 5 tokens (inclusive).
            # Shortest being: foo =
            # Longest being: const foo:Bar =
            for i in range(6):
                token = self.lookAhead(i)
                if token is not None and token.type == Tokens.equal:
                    return self.parseAssignment()
        return self.parseValue()

    def parseValue(self):
        values = [self.parseUnaryOperation()]
        operations = []

        while True:
            token = self.strip([Tokens.comment])

            if token and token.type in BINARY_OPERATION_TOKENS:
                operations.append(self.next())
                values.append(self.parseUnaryOperation())
            else:
                break

        return self.parseBinaryOperation(values, operations)

    def parseBinaryOperation(self, values, operations, operation_index = 0):
        if len(values) == 1:
            return values[0]

        if operation_index == len(BINARY_OPERATIONS):
            raise InternalError("Unparsed operation {}".format(values))

        # Accumulate values from higher order operations
        # Separated by current order operations
        operation_values = []
        operation_operations = []

        previous_index = 0
        for index, operation in enumerate(operations):
            if operation.type in BINARY_OPERATIONS[operation_index]:
                operation_operations.append(operation)

                operation_values.append(self.parseBinaryOperation(
                    values[previous_index:index + 1],
                    operations[previous_index:index],
                    operation_index + 1,
                ))
                previous_index = index + 1
        operation_values.append(self.parseBinaryOperation(
            values[previous_index:],
            operations[previous_index:],
            operation_index + 1,
        ))

        # Accumulate operations (left to right)
        lhs = operation_values[0]
        for index, operation in enumerate(operation_operations):
            rhs = operation_values[index + 1]
            lhs = lekvar.Call(lekvar.Attribute(lhs, operation.data), [rhs], None, operation)

        return lhs

    def parseUnaryOperation(self):
        # Collect prefix unary operations
        operations = []
        while True:
            token = self.strip([Tokens.comment])

            if token is None:
                break

            if token.type in UNARY_OPERATION_TOKENS:
                operations.insert(0, self.next())
            else:
                break

        value = self.parseSingleValue()

        # Make prefix operations
        for operation in operations:
            value = lekvar.Call(lekvar.Attribute(value, operation.data), [], None, operation)

        # Postfix unary operations
        while True:
            token = self.strip([Tokens.comment])

            if token is None:
                break

            if token.type == Tokens.group_start:
                value = self.parseCall(value)
            elif token.type == Tokens.dot:
                value = self.parseAttribute(value)
            elif token.type == Tokens.as_kwd:
                value = self.parseCast(value)
            else:
                break

        return value

    def parseSingleValue(self):
        # Ignore comments and newlines until a value is reached
        token = self.strip([Tokens.comment])

        # EOF handling
        if token is None:
            raise SyntaxError("Expected value before EOF") #TODO: Add token reference

        # Identify the kind of value
        if token.type == Tokens.def_kwd:
            return self.parseMethod()
        elif token.type == Tokens.class_kwd:
            return self.parseClass()
        elif token.type == Tokens.module_kwd:
            return self.parseModule()
        elif token.type == Tokens.identifier:
            token = self.next()
            return lekvar.Reference(token.data, [token])
        elif token.type in (Tokens.integer, Tokens.dot):
            return self.parseNumber()
        elif token.type in (Tokens.true_kwd, Tokens.false_kwd):
            return self.parseConstant()
        elif token.type == Tokens.string:
            token = self.next()
            return lekvar.Literal(token.data, lekvar.Reference("String"), [token])
        elif token.type == Tokens.format_string:
            token = self.next()
            return lekvar.Literal(token.data.encode("UTF-8").decode("unicode-escape"),
                lekvar.Reference("String"), [token])
        elif token.type == Tokens.group_start:
            return self.parseGrouping()

        self._unexpected(token)

    def parseGrouping(self):
        token = self.next()
        assert token.type == Tokens.group_start

        value = self.parseValue()

        self.expect(Tokens.group_end)

        return value

    def parseConstant(self):
        token = self.next()

        if token.type == Tokens.true_kwd:
            return lekvar.Literal(True, lekvar.Reference("Bool"))
        elif token.type == Tokens.false_kwd:
            return lekvar.Literal(False, lekvar.Reference("Bool"))
        else:
            raise InternalError("Invalid constant token type")

    def parseComment(self):
        token = self.next()
        assert token.type == Tokens.comment
        return lekvar.Comment(token.data, [token])

    def parseNumber(self):
        tokens = [self.next()]

        # Float starting with a dot
        if tokens[0].type == Tokens.dot:

            token = self.next()
            if token.type != Tokens.integer:
                self._unexpected(token)

            tokens.append(token)
            value = float("." + token.data.replace("_", ""))
            return lekvar.Literal(value, lekvar.Reference("Real"), tokens)

        assert tokens[0].type == Tokens.integer

        token = self.lookAhead()

        # Float with dot in the middle
        if token is not None and token.type == Tokens.dot:
            tokens.append(self.next())

            value = float(tokens[0].data.replace("_", "") + ".")

            token = self.next()
            tokens.append(token)

            if token.type == Tokens.integer:
                value += float("." + token.data.replace("_", ""))
            else:
                self._unexpected(token)

            return lekvar.Literal(value, lekvar.Reference("Real"), tokens)

        # Integer
        else:
            value = int(tokens[0].data.replace("_", ""))
            return lekvar.Literal(value, lekvar.Reference("Int"), tokens)

    def parseMethod(self):
        # starting keyword should have already been identified
        tokens = [self.next()]
        assert tokens[0].type == Tokens.def_kwd

        # Parse different kinds of methods

        # Non cast operations
        if self.lookAhead(2).type not in [Tokens.as_kwd, Tokens.typeof]:
            # Binary Operations
            if self.lookAhead().type == Tokens.self_kwd:
                tokens.append(self.next())

                token = self.next()
                if token.type not in BINARY_OPERATION_TOKENS:
                    raise SyntaxError("{} is not a valid operation".format(token), [token])
                name = token.data

                tokens.append(token)

                arguments = [self.parseVariable()]
                default_values = [None]
            # Unary Operations
            elif self.lookAhead(2).type == Tokens.self_kwd:
                token = self.next()
                if token.type not in UNARY_OPERATION_TOKENS:
                    raise SyntaxError("{} is not a valid operation".format(token), [token])
                name = token.data

                tokens.append(token)
                tokens.append(self.next())

                arguments = []
                default_values = []
            # Normal named methods
            else:
                name = self.expect(Tokens.identifier, tokens).data
                arguments, default_values = self.parseMethodArguments()

            return_type = self.parseTypeSig(Tokens.returns)

        # Cast operations
        else:
            self.expect(Tokens.self_kwd, tokens)

            # Explicit casts
            if self.lookAhead().type == Tokens.as_kwd:
                tokens.append(self.next())

                name = "as"

                arguments = []
                default_values = []
            # Implicit casts
            else:
                #TODO
                raise InternalError()

            return_type = self.parseSingleValue()

        return self.parseMethodBody(name, arguments, default_values, return_type, tokens)

    def parseConstructor(self):
        # starting keyword should have already been identified
        tokens = [self.next()]
        assert tokens[0].type == Tokens.new_kwd

        name = ""
        arguments, default_values = self.parseMethodArguments()

        return self.parseMethodBody(name, arguments, default_values, None, tokens)

    def parseMethodBody(self, name, arguments, default_values, return_type, tokens):
        # Parse instructions
        instructions = []

        while True:
            token = self.lookAhead()

            if token is None:
                raise SyntaxError("Expected `end` before EOF for method", tokens)

            if token.type == Tokens.end_kwd:
                tokens.append(self.next())
                break
            instructions.append(self.parseLine())

        # Create method with default arguments
        overloads = [lekvar.Function("", arguments, instructions, return_type, tokens)]

        in_defaults = True
        for index, value in enumerate(reversed(default_values)):
            index = -index - 1
            if in_defaults:
                if value is None:
                    in_defaults = False
                else:
                    # Copy arguments
                    args = [arg.copy() for arg in arguments[:index]]

                    # Add an overload calling the previous overload with the default argument
                    overloads.append(
                        lekvar.Function("", args, [
                            lekvar.Call(
                                overloads[-1],
                                # Add non-default arguments with the default value
                                args + [default_values[index]],
                            )
                        ], return_type, tokens)
                    )
            else:
                # Check for default arguments before a non-defaulted argument
                if value is not None:
                    raise SyntaxError("Cannot have non-defaulted arguments after defaulted ones", value.tokens)

        return lekvar.Method(name, overloads)

    def parseMethodArguments(self):
        arguments, default_values = [], []

        token = self.next()

        # Arguments start with "("
        if token.type != Tokens.group_start:
            self._unexpected(token)

        if self.lookAhead().type != Tokens.group_end: # Allow for no arguments

            # Parse arguments
            while True:
                arguments.append(self.parseVariable())

                # Parse default arguments
                token = self.next()
                if token.type == Tokens.equal:
                    default_values.append(self.parseValue())
                    token = self.next()
                else:
                    default_values.append(None)

                # Arguments separated by comma
                if token.type == Tokens.comma:
                    continue
                # Arguments end with ")"
                elif token.type == Tokens.group_end:
                    break
                else:
                    self._unexpected(token)
        else:
            self.next()

        return arguments, default_values

    def parseClass(self):
        # class should have already been identified
        tokens = [self.next()]
        assert tokens[0].type == Tokens.class_kwd

        name = self.expect(Tokens.identifier, tokens).data

        constructor = None
        attributes = {}

        while True:
            token = self.strip([Tokens.comment])

            if token is None:
                raise SyntaxError("Expected `end` before EOF for class", tokens)

            elif token.type == Tokens.end_kwd:
                tokens.append(self.next())
                break

            elif token.type == Tokens.def_kwd:
                value = self.parseMethod()

            elif token.type == Tokens.new_kwd:
                meth = self.parseConstructor()
                if constructor is not None:
                    constructor.assimilate(meth)
                else:
                    constructor = meth
                continue

            elif token.type == Tokens.identifier:
                value = self.parseVariable()

            else:
                self._unexpected(token)

            self.addChild(attributes, value)

        return lekvar.Class(name, constructor, list(attributes.values()))

    def parseWhile(self):
        tokens = [self.next()]
        assert tokens[0].type == Tokens.while_kwd

        condition = self.parseValue()

        instructions = []

        while True:
            token = self.lookAhead()

            if token is None:
                raise SyntaxError("Expected `end` before EOF for while loop", tokens)

            elif token.type == Tokens.end_kwd:
                tokens.append(self.next())
                break

            instructions.append(self.parseLine())

        branch = lekvar.Branch(condition, [], [lekvar.Break()])
        return lekvar.Loop([branch] + instructions, tokens)

    def parseLoop(self):
        tokens = [self.next()]
        assert tokens[0].type == Tokens.loop_kwd

        instructions = []

        while True:
            token = self.lookAhead()

            if token is None:
                raise SyntaxError("Expected `end` before EOF for loop", tokens)

            elif token.type == Tokens.end_kwd:
                tokens.append(self.next())
                break

            instructions.append(self.parseLine())

        return lekvar.Loop(instructions, tokens)

    def parseBreak(self):
        token = self.next()

        assert token.type == Tokens.break_kwd

        return lekvar.Break([token])

    def parseBranch(self):
        tokens = [self.next()]
        assert tokens[0].type == Tokens.if_kwd

        condition = self.parseValue()

        if_instructions = []

        while True:
            token = self.lookAhead()

            if token is None:
                raise SyntaxError("Expected `end` or `else` before EOF for if branch", tokens)

            elif token.type == Tokens.end_kwd:
                tokens.append(self.next())
                return lekvar.Branch(condition, if_instructions, [], tokens)

            elif token.type == Tokens.else_kwd:
                tokens.append(self.next())
                break

            if_instructions.append(self.parseLine())

        else_instructions = []

        while True:
            token = self.lookAhead()

            if token is None:
                raise SyntaxError("Expected `end` before EOF for else branch", tokens)

            elif token.type == Tokens.end_kwd:
                tokens.append(self.next())
                return lekvar.Branch(condition, if_instructions, else_instructions, tokens)

            else_instructions.append(self.parseLine())

    # Parse a variable, with optional type signature
    def parseVariable(self):
        tokens = []

        if self.lookAhead().type == Tokens.const_kwd:
            tokens.append(self.next())
            constant = True
        else:
            constant = False

        name = self.expect(Tokens.identifier, tokens).data

        type = self.parseTypeSig()

        return lekvar.Variable(name, type, constant, tokens)

    # Parse an optional type signature
    def parseTypeSig(self, typeof = Tokens.typeof):
        if self.lookAhead().type != typeof:
            return None
        self.next()

        return self.parseValue()

    # Parse a function call
    def parseCall(self, called):
        tokens = [self.next()]
        assert tokens[0].type == Tokens.group_start

        arguments = []
        token = self.lookAhead()
        if token is None:
            self.expect(Tokens.group_end)

        if token.type != Tokens.group_end:

            # Parse arguments
            while True:
                arguments.append(self.parseValue())

                token = self.next()
                if token.type == Tokens.comma:
                    continue
                elif token.type == Tokens.group_end:
                    tokens.append(token)
                    break
                else:
                    self._unexpected(token)
        else:
            self.next()

        return lekvar.Call(called, arguments, None, tokens)

    # Parse a return statement
    def parseReturn(self):
        # return keyword is expected to be parsed
        tokens = [self.next()]
        assert tokens[0].type == Tokens.return_kwd

        try:
            value = self.parseValue()
        except SyntaxError:
            value = None

        return lekvar.Return(value, tokens)

    # Parse a assignment
    def parseAssignment(self):
        variable = self.parseVariable()

        tokens = [self.next()]
        assert tokens[0].type == Tokens.equal

        value = self.parseValue()
        return lekvar.Assignment(variable, value, tokens)

    def parseAttribute(self, value):
        tokens = [self.next()]
        assert tokens[0].type == Tokens.dot

        attribute = self.expect(Tokens.identifier, tokens).data
        return lekvar.Attribute(value, attribute, tokens)

    def parseCast(self, value):
        token = self.next()
        assert token.type == Tokens.as_kwd

        type = self.parseSingleValue()
        return lekvar.Call(lekvar.Attribute(value, token.data), [], type, [token])

    def parseImport(self):
        tokens = [self.next()]
        assert tokens[0].type == Tokens.import_kwd

        path = self.parseImportPath(tokens)

        name = None
        if self.lookAhead().type == Tokens.as_kwd:
            tokens.append(self.next())

            name = self.expect(Tokens.identifier, tokens).data

        return lekvar.Import(path, name, tokens)

    def parseImportPath(self, tokens):
        path = []

        # Paths can start with any number of dots
        while self.lookAhead().type == Tokens.dot:
            tokens.append(self.next())
            path.append(".")

        # Then identifiers separated by dots
        while True:
            token = self.expect(Tokens.identifier, tokens)
            path.append(token.data)

            token = self.lookAhead()
            # Check for next path element
            if token.type == Tokens.dot:
                tokens.append(self.next())
            # Otherwise stop parsing for a path
            else:
                return path
