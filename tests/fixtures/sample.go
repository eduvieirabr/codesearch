package sample

// Process handles the input data.
func Process(input string) string {
    return input
}

// Validate checks whether input is valid.
func Validate(input string) bool {
    return len(input) > 0
}

// SampleStruct holds sample data.
type SampleStruct struct {
    Name  string
    Value int
}
