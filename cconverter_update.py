from pycparser import c_parser, c_ast, c_generator
import hashlib
import re

class cConverter:
    def __init__(self):
        self.function_ptr_vars = set()  # Function pointer variable names
        self.assignments = {}  # Tracks last function assigned to each pointer
        self.generator = c_generator.CGenerator()
        self.ast_cache = {}  # Cache for parsed ASTs

    def analyze_ast(self, ast):
        """Analyze AST to collect function pointer info and assignments"""
        for node in ast.ext:
            if isinstance(node, c_ast.FuncDef):
                self.assignments.clear()  # Reset assignments for each function
                self._collect_function_ptr_info(node.body)

    def _collect_function_ptr_info(self, compound_node):
        """Collect function pointer declarations and assignments"""
        if not isinstance(compound_node, c_ast.Compound) or not compound_node.block_items:
            return

        for item in compound_node.block_items:
            # Collect function pointer declarations
            if isinstance(item, c_ast.Decl) and isinstance(item.type, c_ast.PtrDecl):
                if self._is_function_pointer(item.type):
                    self.function_ptr_vars.add(item.name)
                    self.assignments[item.name] = None  # Initialize with no assignment

            # Collect assignments
            elif isinstance(item, c_ast.Assignment):
                self._process_assignment(item)

            # Handle control structures
            elif isinstance(item, c_ast.If):
                if item.iftrue:
                    self._collect_function_ptr_info(item.iftrue)
                if item.iffalse:
                    self._collect_function_ptr_info(item.iffalse)
            elif isinstance(item, (c_ast.While, c_ast.DoWhile, c_ast.For)):
                self._collect_function_ptr_info(item.stmt)
            elif isinstance(item, c_ast.Compound):
                self._collect_function_ptr_info(item)

    def _is_function_pointer(self, type_node):
        """Check if a type node is a function pointer"""
        return isinstance(type_node, c_ast.PtrDecl) and isinstance(type_node.type, c_ast.FuncDecl)

    def _process_assignment(self, assign_node):
        """Process function pointer assignments"""
        if (isinstance(assign_node.lvalue, c_ast.ID) and
            assign_node.lvalue.name in self.function_ptr_vars and
            isinstance(assign_node.rvalue, c_ast.ID)):
            var_name = assign_node.lvalue.name
            func_name = assign_node.rvalue.name
            self.assignments[var_name] = func_name

    def transform_ast(self, ast):
        """Transform AST to remove function pointers and use direct calls"""
        for node in ast.ext:
            if isinstance(node, c_ast.FuncDef):
                self.assignments.clear()  # Reset assignments for each function
                self._transform_block(node.body)
        return ast

    def _transform_block(self, compound_node):
        """Transform a compound statement, removing function pointers"""
        if not isinstance(compound_node, c_ast.Compound) or not compound_node.block_items:
            return

        new_items = []
        for item in compound_node.block_items:
            # Skip function pointer declarations
            if isinstance(item, c_ast.Decl) and item.name in self.function_ptr_vars:
                continue

            # Process assignments to update tracking, but skip in output
            if isinstance(item, c_ast.Assignment) and isinstance(item.lvalue, c_ast.ID):
                if item.lvalue.name in self.function_ptr_vars:
                    self._process_assignment(item)
                    continue

            # Transform function pointer calls
            elif isinstance(item, c_ast.FuncCall) and isinstance(item.name, c_ast.ID):
                var_name = item.name.name
                if var_name in self.function_ptr_vars:
                    func_name = self.assignments.get(var_name)
                    if func_name:
                        new_items.append(c_ast.FuncCall(
                            c_ast.ID(func_name),
                            item.args if item.args else c_ast.ExprList([])
                        ))
                    else:
                        print(f"Warning: No assignment found for function pointer {var_name}")
                else:
                    new_items.append(item)

            # Handle control structures
            elif isinstance(item, c_ast.If):
                if item.iftrue:
                    self._transform_block(item.iftrue)
                if item.iffalse:
                    self._transform_block(item.iffalse)
                new_items.append(item)
            elif isinstance(item, (c_ast.While, c_ast.DoWhile, c_ast.For)):
                self._transform_block(item.stmt)
                new_items.append(item)
            elif isinstance(item, c_ast.Compound):
                self._transform_block(item)
                new_items.append(item)
            else:
                new_items.append(item)

        compound_node.block_items = new_items

    def _preprocess_c_code(self, c_code):
        """Clean and preprocess C code"""
        lines = [line for line in c_code.split('\n') if not line.strip().startswith('#')]
        processed_code = '\n'.join(lines)
        processed_code = re.sub(r"printf\('(.*?)'\)", r'printf("\1")', processed_code)
        return processed_code

    def convert(self, c_code):
        """Convert C code to remove function pointers and use direct calls"""
        try:
            code_hash = hashlib.md5(c_code.encode()).digest()
            if code_hash in self.ast_cache:
                ast = self.ast_cache[code_hash]
            else:
                clean_code = self._preprocess_c_code(c_code)
                parser = c_parser.CParser()
                try:
                    ast = parser.parse(clean_code)
                except Exception:
                    fake_code = f"void printf(const char *format, ...);\n{clean_code}"
                    ast = parser.parse(fake_code)
                self.ast_cache[code_hash] = ast

            self.function_ptr_vars.clear()
            self.analyze_ast(ast)  # First pass: collect declarations and initial assignments
            transformed_ast = self.transform_ast(ast)  # Second pass: transform with updated assignments
            return self.generator.visit(transformed_ast)

        except Exception as e:
            return f"Error converting code: {str(e)}"




class ReturnConverter:
    def __init__(self):
        self.generator = c_generator.CGenerator()

    def _generate_unique_name(self, func, base_name="out"):
        existing_names = set()

        # Collect names from parameters
        if func.decl.type.args:
            for param in func.decl.type.args.params:
                if isinstance(param, c_ast.Decl):
                    existing_names.add(param.name)

        # Collect names from declarations inside the body
        if func.body and func.body.block_items:
            for stmt in func.body.block_items:
                if isinstance(stmt, c_ast.Decl):
                    existing_names.add(stmt.name)

        # Generate unique name
        suffix = 1
        name = base_name
        while name in existing_names:
            name = f"{base_name}{suffix}"
            suffix += 1
        return name

    def transform(self, code):
        parser = c_parser.CParser()
        ast = parser.parse(code)

        for ext in ast.ext:
            if isinstance(ext, c_ast.FuncDef):
                func = ext

                # Skip void functions
                if func.decl.type.type.type.names == ['void']:
                    continue

                # Get return type
                return_type = func.decl.type.type.type.names[0]

                # Change return type to void
                func.decl.type.type.type.names = ['void']

                # Get a unique name for the output variable
                out_name = self._generate_unique_name(func, "out")

                # Add output parameter
                out_param = c_ast.Decl(
                    name=out_name,
                    quals=[],
                    align = None,
                    storage=[],
                    funcspec=[],
                    type=c_ast.PtrDecl(
                        quals=[],
                        type=c_ast.TypeDecl(
                            declname=out_name,
                            quals=[],
                            align=None,
                            type=c_ast.IdentifierType(names=[return_type])
                        )
                    ),
                    init=None,
                    bitsize=None
                )
                if func.decl.type.args:
                    func.decl.type.args.params.insert(0, out_param)
                else:
                    func.decl.type.args = c_ast.ParamList(params=[out_param])

                # Replace return statements
                if func.body and func.body.block_items:
                    new_body = []
                    for stmt in func.body.block_items:
                        if isinstance(stmt, c_ast.Return) and stmt.expr:
                            assign_stmt = c_ast.Assignment(
                                op='=',
                                lvalue=c_ast.UnaryOp(op='*', expr=c_ast.ID(out_name)),
                                rvalue=stmt.expr
                            )
                            new_body.append(assign_stmt)
                        elif not isinstance(stmt, c_ast.Return):
                            new_body.append(stmt)
                    func.body.block_items = new_body

        return self.generator.visit(ast)

        

# Test code
if __name__ == "__main__":
    c_code2 = """
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
    c_code = """
    void hello() { printf("Hello\\n"); }
    void goodbye() { printf("Goodbye\\n"); }
    void nested() { printf("Nested\\n"); }
    int main() {
        void (*fp)();
        void (*fp2)();
        int i = 0;
        fp = hello;
        for(i = 0; i < 2; i++) {
            while(i < 1) {
                fp();
                fp = goodbye;
            }
            do {
                fp2 = nested;
                fp2();
            } while(i < 1);
        }
        fp();
        return 0;
    }
    """

    print("Output for c_code2:")
    print(ReturnConverter().transform(cConverter().convert(c_code2)))
    print("\nOutput for c_code:")
    print(ReturnConverter().transform(cConverter().convert(c_code)))
   

