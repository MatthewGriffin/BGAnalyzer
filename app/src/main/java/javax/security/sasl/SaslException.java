package javax.security.sasl;

import java.io.IOException;

/** Standard Java exception type that Android leaves out. See {@link SaslClient}. */
public class SaslException extends IOException {
    public SaslException() {
        super();
    }

    public SaslException(String detail) {
        super(detail);
    }

    public SaslException(String detail, Throwable ex) {
        super(detail, ex);
    }
}
