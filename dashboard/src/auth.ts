import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"
import Google from "next-auth/providers/google"
import GitHub from "next-auth/providers/github"

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://api.engramia.dev"

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null
        try {
          const res = await fetch(`${BACKEND_URL}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              email: credentials.email,
              password: credentials.password,
            }),
          })
          if (!res.ok) return null
          const data = await res.json()
          return {
            id: data.user_id,
            email: data.email,
            tenantId: data.tenant_id,
            accessToken: data.access_token,
            refreshToken: data.refresh_token,
          }
        } catch {
          return null
        }
      },
    }),
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
    }),
    GitHub({
      clientId: process.env.GITHUB_CLIENT_ID!,
      clientSecret: process.env.GITHUB_CLIENT_SECRET!,
    }),
  ],
  callbacks: {
    async jwt({ token, user, account }) {
      // Initial sign in via Credentials
      if (user) {
        token.userId = user.id
        token.tenantId = (user as any).tenantId
        token.accessToken = (user as any).accessToken
        token.refreshToken = (user as any).refreshToken
      }
      // OAuth providers — exchange with backend
      if (
        (account?.provider === "google" || account?.provider === "github") &&
        account.id_token
      ) {
        try {
          const res = await fetch(`${BACKEND_URL}/auth/oauth`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              provider: account.provider,
              provider_token: account.id_token,
              email: token.email,
              name: token.name,
            }),
          })
          if (res.ok) {
            const data = await res.json()
            token.userId = data.user_id
            token.tenantId = data.tenant_id
            token.accessToken = data.access_token
            token.apiKey = data.api_key // only on first registration
          }
        } catch {}
      }
      // GitHub uses access_token instead of id_token
      if (account?.provider === "github" && account.access_token && !account.id_token) {
        try {
          const res = await fetch(`${BACKEND_URL}/auth/oauth`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              provider: "github",
              provider_token: account.access_token,
              email: token.email,
              name: token.name,
            }),
          })
          if (res.ok) {
            const data = await res.json()
            token.userId = data.user_id
            token.tenantId = data.tenant_id
            token.accessToken = data.access_token
            token.apiKey = data.api_key
          }
        } catch {}
      }
      return token
    },
    async session({ session, token }) {
      session.user.id = token.userId as string
      ;(session as any).tenantId = token.tenantId
      ;(session as any).accessToken = token.accessToken
      ;(session as any).apiKey = token.apiKey
      return session
    },
  },
  pages: {
    signIn: "/login",
    error: "/login",
  },
  session: { strategy: "jwt" },
  secret: process.env.NEXTAUTH_SECRET,
})
