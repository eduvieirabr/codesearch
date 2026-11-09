function greet(name: string): string {
    return `Hello, ${name}!`;
}

function farewell(name: string): string {
    return `Goodbye, ${name}!`;
}

class Greeter {
    hello(name: string): string {
        return greet(name);
    }
}
