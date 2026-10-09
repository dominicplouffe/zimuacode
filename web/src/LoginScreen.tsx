export function LoginScreen({ error }: { error?: string }) {
  return (
    <div className="login">
      <div className="login-card">
        <h1>Zimua Code</h1>
        <p>Your repositories, branches, PRs and coding agents in one place.</p>
        <a className="button" href="/api/auth/login">
          Sign in with GitHub
        </a>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}
