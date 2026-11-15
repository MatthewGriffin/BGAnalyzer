package javax.security.sasl;

/**
 * Android does not ship the javax.security.sasl package, and the MongoDB driver's password login
 * (SCRAM) implements this interface. This copy of the standard Java interface lets the driver load.
 * The driver brings its own SCRAM code, so nothing else from the package is needed.
 */
public interface SaslClient {
    String getMechanismName();

    boolean hasInitialResponse();

    byte[] evaluateChallenge(byte[] challenge) throws SaslException;

    boolean isComplete();

    byte[] unwrap(byte[] incoming, int offset, int len) throws SaslException;

    byte[] wrap(byte[] outgoing, int offset, int len) throws SaslException;

    Object getNegotiatedProperty(String propName);

    void dispose() throws SaslException;
}
