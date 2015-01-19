from .lekvar.lekvar import *

def helloWorld():
    # external puts as print
    # def helloWorld() {
    #     print("Hello World!")
    # }
    # helloWorld()
    #
    #=> Hello World!\n

    return Module( {
        "print" : ExternalFunction("puts", [LLVMType("String")], LLVMType("Int")), # external puts as print
        "helloWorld": Function([], [ # def helloWorld() {
            Call("print", [ # print(
                Literal( "Hello World!", LLVMType("String") ) # "Hello World!"
            ] ) # )
        ], None), # }
    }, Function([], [
        Call("helloWorld", []) # helloWorld()
    ], None))

def functionCalls():
    # external puts as print
    # def reprint(one:String, two:String) {
    #     print(one)
    #     return two
    #     print(two)
    # }
    # print(reprint("1", "2"))
    #
    #=> 1\n2\n

    return Module( {
        "print" : ExternalFunction("puts", [LLVMType("String")], LLVMType("Int")), # external puts as print
        "reprint": Function( [ Variable("one", LLVMType("String")), Variable("two", LLVMType("String")) ], [
            Call("print", [
                Reference("one")
            ] ),
            Return(Reference("two")),
            Call("print", [
                Reference("two")
            ] )
        ] )
    }, Function([], [
        Call("print", [
            Call("reprint", [
                Literal("1", LLVMType("String")),
                Literal("2", LLVMType("String"))
            ] )
        ] )
    ] ))