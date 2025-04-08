from pycparser import c_parser, c_ast, c_generator
import hashlib
import re

class cConverter:
    def __init__(self):
        self.function_ptr_vars = set()
        self.generator = c_generator.CGenerator()
        self.ast_cache = {}

    def analyze_ast(self, ast):
        """Analyze AST to collect function pointer info"""
        for node in ast.ext:
            if isinstance(node, c_ast.FuncDef):
                self._collect_function_ptr_info(node.body)

    def _collect_function_ptr_info(self, compound_node):
        """Collect function pointer declarations"""
        if not isinstance(compound_node, c_ast.Compound) or not compound_node.block_items:
            return

        for item in compound_node.block_items:
            if isinstance(item, c_ast.Decl) and isinstance(item.type, c_ast.PtrDecl):
                if self._is_function_pointer(item.type):
                    self.function_ptr_vars.add(item.name)
            elif isinstance(item, (c_ast.While, c_ast.DoWhile, c_ast.For)):
                if isinstance(item.stmt, c_ast.Compound):
                    self._collect_function_ptr_info(item.stmt)
            elif isinstance(item, c_ast.If):
                if item.iftrue and isinstance(item.iftrue, c_ast.Compound):
                    self._collect_function_ptr_info(item.iftrue)
                if item.iffalse and isinstance(item.iffalse, c_ast.Compound):
                    self._collect_function_ptr_info(item.iffalse)
            elif isinstance(item, c_ast.Compound):
                self._collect_function_ptr_info(item)

    def _is_function_pointer(self, type_node):
        """Check if a type node is a function pointer"""
        return isinstance(type_node, c_ast.PtrDecl) and isinstance(type_node.type, c_ast.FuncDecl)

    def _track_assignments_in_block(self, compound_node, assignments_state):
        """Track assignments and transform calls with current state"""
        if not isinstance(compound_node, c_ast.Compound) or not compound_node.block_items:
            return assignments_state

        new_items = []
        current_assignments = assignments_state.copy()

        for item in compound_node.block_items:
            if isinstance(item, c_ast.Decl) and item.name in self.function_ptr_vars:
                continue

            if isinstance(item, c_ast.Assignment) and isinstance(item.lvalue, c_ast.ID):
                var_name = item.lvalue.name
                if var_name in self.function_ptr_vars and isinstance(item.rvalue, c_ast.ID):
                    current_assignments[var_name] = item.rvalue.name
                    continue

            elif isinstance(item, c_ast.FuncCall) and isinstance(item.name, c_ast.ID):
                var_name = item.name.name
                if var_name in self.function_ptr_vars and var_name in current_assignments:
                    new_items.append(c_ast.FuncCall(c_ast.ID(current_assignments[var_name]), item.args))
                    continue

            elif isinstance(item, c_ast.If):
                iftrue_call = None
                iffalse_call = None
                if item.iftrue and isinstance(item.iftrue, c_ast.Assignment) and \
                   isinstance(item.iftrue.lvalue, c_ast.ID) and \
                   item.iftrue.lvalue.name in self.function_ptr_vars and \
                   isinstance(item.iftrue.rvalue, c_ast.ID):
                    iftrue_call = item.iftrue.rvalue.name
                if item.iffalse and isinstance(item.iffalse, c_ast.Assignment) and \
                   isinstance(item.iffalse.lvalue, c_ast.ID) and \
                   item.iffalse.lvalue.name in self.function_ptr_vars and \
                   isinstance(item.iffalse.rvalue, c_ast.ID):
                    iffalse_call = item.iffalse.rvalue.name

                if iftrue_call or iffalse_call:
                    continue
                else:
                    if item.iftrue and isinstance(item.iftrue, c_ast.Compound):
                        self._track_assignments_in_block(item.iftrue, current_assignments.copy())
                    if item.iffalse and isinstance(item.iffalse, c_ast.Compound):
                        self._track_assignments_in_block(item.iffalse, current_assignments.copy())
                    new_items.append(item)

            elif isinstance(item, (c_ast.While, c_ast.DoWhile, c_ast.For)):
                if isinstance(item.stmt, c_ast.Compound):
                    new_state = self._track_assignments_in_block(item.stmt, current_assignments.copy())
                    current_assignments.update(new_state)
                new_items.append(item)

            elif isinstance(item, c_ast.Compound):
                self._track_assignments_in_block(item, current_assignments.copy())
                new_items.append(item)

            else:
                new_items.append(item)

        compound_node.block_items = new_items
        return current_assignments

    def transform_ast(self, ast):
        """Transform AST to remove function pointers and use direct calls"""
        initial_assignments = {}
        for node in ast.ext:
            if isinstance(node, c_ast.FuncDef):
                if node.body.block_items:
                    new_items = []
                    i = 0
                    while i < len(node.body.block_items):
                        item = node.body.block_items[i]
                        if isinstance(item, c_ast.Assignment) and isinstance(item.lvalue, c_ast.ID):
                            var_name = item.lvalue.name
                            if var_name in self.function_ptr_vars and isinstance(item.rvalue, c_ast.ID):
                                initial_assignments[var_name] = item.rvalue.name
                                i += 1
                                continue
                        elif (isinstance(item, c_ast.If) and i + 1 < len(node.body.block_items) and
                              isinstance(node.body.block_items[i + 1], c_ast.FuncCall) and
                              isinstance(node.body.block_items[i + 1].name, c_ast.ID) and
                              node.body.block_items[i + 1].name.name in self.function_ptr_vars):
                            iftrue_call = None
                            iffalse_call = None
                            if item.iftrue and isinstance(item.iftrue, c_ast.Assignment) and \
                               isinstance(item.iftrue.lvalue, c_ast.ID) and \
                               isinstance(item.iftrue.rvalue, c_ast.ID):
                                iftrue_call = c_ast.FuncCall(item.iftrue.rvalue, None)
                            if item.iffalse and isinstance(item.iffalse, c_ast.Assignment) and \
                               isinstance(item.iffalse.lvalue, c_ast.ID) and \
                               isinstance(item.iffalse.rvalue, c_ast.ID):
                                iffalse_call = c_ast.FuncCall(item.iffalse.rvalue, None)
                            if iftrue_call or iffalse_call:
                                new_items.append(c_ast.If(item.cond, iftrue_call, iffalse_call))
                                i += 2
                                continue
                        new_items.append(item)
                        i += 1
                    node.body.block_items = new_items
                    self._track_assignments_in_block(node.body, initial_assignments)
        return ast

    def _preprocess_c_code(self, c_code):
        """Minimal preprocessing - just ensure proper formatting"""
        # Preserve everything, just normalize whitespace
        processed_code = '\n'.join(line.strip() for line in c_code.split('\n') if line.strip())
        return processed_code

    def convert(self, c_code):
        """Convert C code to remove function pointers and use direct calls"""
        try:
            code_hash = hashlib.md5(c_code.encode()).hexdigest()
            if code_hash in self.ast_cache:
                ast = self.ast_cache[code_hash]
            else:
                clean_code = self._preprocess_c_code(c_code)
                parser = c_parser.CParser()
                # Add full preamble with stdio.h-like declarations
                preamble = """
                typedef unsigned long size_t;
                typedef int FILE;
                int printf(const char *format, ...);
                """
                try:
                    ast = parser.parse(preamble + clean_code)
                except Exception as e:
                    return f"Error parsing code: {str(e)}"
                self.ast_cache[code_hash] = ast

            self.function_ptr_vars.clear()
            self.analyze_ast(ast)
            transformed_ast = self.transform_ast(ast)
            # Only output the user-defined functions, skip preamble
            filtered_ast = c_ast.FileAST([node for node in transformed_ast.ext
                                        if isinstance(node, c_ast.FuncDef)])
            return self.generator.visit(filtered_ast)

        except Exception as e:
            return f"Error converting code: {str(e)}"

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

    converter = cConverter()
    print("Output for c_code2:")
    print(converter.convert(c_code2))
    print("\nOutput for c_code:")
    print(converter.convert(c_code))
