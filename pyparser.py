from pycparser import c_parser, c_ast

#C code as a multi-line string
c_code = """
void foo() {printf('foo');}
void bar() {printf('bar');}

int main() {
    void (*fp)();
    int input = 0;

    if (input == 0)
        fp = foo;
    else
        fp = bar;

    fp();
    return 0;
}
"""

#Parse the code string
parser = c_parser.CParser()
ast = parser.parse(c_code)

#Print the AST
ast.show()

