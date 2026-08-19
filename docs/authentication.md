# Authentication and Authorization

```text
Email + password
      |
      v
normalized email + Argon2id verification
      |
      v
cryptographically random server session
      |
      +-- raw token  -> HttpOnly SameSite cookie
      |
      +-- SHA-256 hash -> PostgreSQL auth_sessions
      |
      v
GET /auth/me -> identity + agency + role + CSRF token
      |
      +-- Agent
      +-- Manager (inherits Agent capabilities)
```

Passwords are verified with Argon2id, a memory-hard password hashing algorithm designed to make stolen password hashes expensive to crack. Login returns the same error for a missing account and a wrong password, and it performs a dummy Argon2 check for a missing account to reduce timing differences.

The session cookie contains only a high-entropy opaque token. JavaScript cannot read it because it is HttpOnly, and the application never puts it in localStorage or sessionStorage. PostgreSQL stores only a SHA-256 lookup hash plus the user, creation/expiry/last-seen timestamps, revocation state, and a hash of the session CSRF value. An expired or revoked session—or one belonging to a disabled user or agency—cannot authenticate.

`last_seen_at` represents persisted recent authenticated activity rather than every individual request. Session resolution updates and commits it only when the stored timestamp is at least five minutes old. This makes the field operationally meaningful while avoiding a PostgreSQL write for every authenticated page/API request.

Cookies are sent automatically, so an attacker could otherwise try to trigger a state-changing request from another site. The frontend therefore sends the session-bound value returned by `/auth/me` in `X-CSRF-Token` on POST, PUT, PATCH, and DELETE requests. The backend compares its hash in constant time before allowing the mutation. CORS additionally permits credentialed browser requests only from the configured frontend origin.

Logout requires CSRF validation, marks the database session revoked, writes an audit event, and clears the cookie. Login also writes an audit event and updates `last_login_at`.

Authorization is enforced by FastAPI dependencies and agency-scoped service queries. Agents can read and change only their assigned operational records. Managers can see agency-wide records and use Manager endpoints. Hiding Manager links in React improves the interface, but it is not a security control: a manually issued Agent request still receives `403 Forbidden` from the backend.
