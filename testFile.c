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