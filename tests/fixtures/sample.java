public class SampleService {

    /** Process input data. */
    public String process(String input) {
        return input.toUpperCase();
    }

    /** Validate the given value. */
    public boolean validate(String value) {
        return value != null && !value.isEmpty();
    }
}
