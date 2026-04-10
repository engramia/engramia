"use client"
import { useState } from "react"
import { signIn } from "next-auth/react"
import Link from "next/link"

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://api.engramia.dev"

export default function RegisterPage() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    if (password.length < 8) { setError("Password must be at least 8 characters"); return }
    if (password !== confirm) { setError("Passwords do not match"); return }
    setLoading(true)
    try {
      const res = await fetch(`${BACKEND_URL}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      })
      const data = await res.json()
      if (!res.ok) { setError(data.detail ?? "Registration failed"); setLoading(false); return }
      // Auto sign-in after registration
      await signIn("credentials", { email, password, redirect: false })
      // Store API key for setup wizard
      sessionStorage.setItem("engramia_new_api_key", data.api_key ?? "")
      window.location.href = "/setup"
    } catch {
      setError("Network error — please try again")
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="w-full max-w-md p-8 bg-gray-900 rounded-2xl border border-gray-800 shadow-xl">
        <div className="mb-8 text-center">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-lg font-bold text-white mb-3">
            E
          </div>
          <h1 className="text-2xl font-bold text-white">Create your account</h1>
          <p className="text-gray-400 mt-1">Start for free, no credit card required</p>
        </div>

        {/* GitHub */}
        <button
          onClick={() => signIn("github", { callbackUrl: "/setup" })}
          className="w-full flex items-center justify-center gap-3 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-white rounded-lg font-medium transition mb-3 border border-gray-700"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
          </svg>
          Continue with GitHub
        </button>

        {/* Google */}
        <button
          onClick={() => signIn("google", { callbackUrl: "/setup" })}
          className="w-full flex items-center justify-center gap-3 px-4 py-2.5 bg-white text-gray-900 rounded-lg font-medium hover:bg-gray-50 transition mb-4"
        >
          <svg width="18" height="18" viewBox="0 0 18 18">
            <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/>
            <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.909-2.259c-.806.54-1.836.86-3.047.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
            <path d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
            <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
          </svg>
          Continue with Google
        </button>

        <div className="relative my-4">
          <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-gray-700" /></div>
          <div className="relative flex justify-center text-sm"><span className="bg-gray-900 px-2 text-gray-500">or</span></div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required
              className="w-full px-3 py-2.5 bg-elevated border border-border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-accent"
              placeholder="you@company.com" />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required
              className="w-full px-3 py-2.5 bg-elevated border border-border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-accent"
              placeholder="Min. 8 characters" />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Confirm Password</label>
            <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} required
              className="w-full px-3 py-2.5 bg-elevated border border-border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-accent"
              placeholder="••••••••" />
          </div>
          {error && <p className="text-red-400 text-sm">{error}</p>}
          <button type="submit" disabled={loading}
            className="w-full py-2.5 bg-accent hover:bg-accent/80 disabled:opacity-50 text-white rounded-lg font-medium transition">
            {loading ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-gray-600">
          By signing up you agree to our{" "}
          <a href="https://engramia.dev/legal/terms" className="underline">Terms</a> and{" "}
          <a href="https://engramia.dev/legal/privacy" className="underline">Privacy Policy</a>.
        </p>
        <p className="mt-3 text-center text-sm text-gray-500">
          Already have an account?{" "}
          <Link href="/login" className="text-accent hover:text-accent/80">Sign in</Link>
        </p>
      </div>
    </div>
  )
}
