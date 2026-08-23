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
      +-- Manager (agency oversight/configuration)
```

Passwords are verified with Argon2id, a memory-hard password hashing algorithm designed to make stolen password hashes expensive to crack. Login returns the same error for a missing account and a wrong password, and it performs a dummy Argon2 check for a missing account to reduce timing differences.

The session cookie contains only a high-entropy opaque token. JavaScript cannot read it because it is HttpOnly, and the application never puts it in localStorage or sessionStorage. PostgreSQL stores only a SHA-256 lookup hash plus the user, creation/expiry/last-seen timestamps, revocation state, and a hash of the session CSRF value. An expired or revoked session—or one belonging to a disabled user or agency—cannot authenticate.

`last_seen_at` represents persisted recent authenticated activity rather than every individual request. Session resolution updates and commits it only when the stored timestamp is at least five minutes old. This makes the field operationally meaningful while avoiding a PostgreSQL write for every authenticated page/API request.

Cookies are sent automatically, so an attacker could otherwise try to trigger a state-changing request from another site. The frontend therefore sends the session-bound value returned by `/auth/me` in `X-CSRF-Token` on POST, PUT, PATCH, and DELETE requests. The backend compares its hash in constant time before allowing the mutation. CORS additionally permits credentialed browser requests only from the configured frontend origin.

Logout requires CSRF validation, marks the database session revoked, writes an audit event, and clears the cookie. Login also writes an audit event and updates `last_login_at`.

Authorization is enforced by FastAPI dependencies and agency-scoped service queries. Agents own operational work and can read and change only their assigned records. Managers have agency-wide visibility and configuration endpoints, including whole-Case assignment/reassignment, but do not inherit Agent-only decision authority: they cannot complete Agent Tasks, apply or dismiss Agent Reviews, complete Cases for Agents, or connect another user's Gmail. Active Tasks and Reviews follow a Manager Case reassignment while terminal creator/completer/reviewer attribution remains historical. Hiding role-specific links in React improves the interface, but it is not a security control: a manually issued unauthorized request still receives `403 Forbidden` from the backend.
