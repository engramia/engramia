# Admin Guide

Operational reference for Engramia platform administrators. For general deployment see [deployment.md](deployment.md), for runbooks see [runbooks/README.md](runbooks/README.md).

---

## Cloud Registration Setup

### Prerequisites

- VPS running with Docker Compose
- Domain `app.engramia.dev` pointing to VPS IP (A record or CNAME)
- Domain `api.engramia.dev` pointing to VPS IP

### 1. Generate NEXTAUTH_SECRET

```bash
openssl rand -hex 32
```

Add to `.env.production`:
```
NEXTAUTH_SECRET=<generated value>
NEXTAUTH_URL=https://app.engramia.dev
```

### 2. GitHub OAuth App

1. Go to https://github.com/settings/developers → OAuth Apps → New OAuth App
2. Fill in:
   - Application name: `Engramia`
   - Homepage URL: `https://app.engramia.dev`
   - Authorization callback URL: `https://app.engramia.dev/api/auth/callback/github`
3. Click **Register application**
4. On the app page: click **Generate a new client secret**
5. Copy both values to `.env.production`:
   ```
   GITHUB_CLIENT_ID=<your client id>
   GITHUB_CLIENT_SECRET=<your client secret>
   ```

### 3. Google OAuth App

1. Go to https://console.cloud.google.com
2. Create a new project (or use existing): `Engramia`
3. Navigate to **APIs & Services** → **OAuth consent screen**
   - User Type: External
   - App name: Engramia
   - User support email: your email
   - Authorized domain: `engramia.dev`
   - Developer contact: your email
   - Save and Continue (skip Scopes, skip Test Users)
   - Submit for verification (or keep in Testing mode for dev)
4. Navigate to **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
   - Application type: Web application
   - Name: `Engramia Dashboard`
   - Authorized JavaScript origins: `https://app.engramia.dev`
   - Authorized redirect URIs: `https://app.engramia.dev/api/auth/callback/google`
5. Copy to `.env.production`:
   ```
   GOOGLE_CLIENT_ID=<your client id>
   GOOGLE_CLIENT_SECRET=<your client secret>
   ```

> **Note:** While in "Testing" mode, only Google accounts added as test users can sign in. Add your own email first. For production, submit the app for Google review (takes 1-7 days).

### 4. Stripe Payment Links

In Stripe Dashboard → Payment Links, create two links:
- Pro Monthly: `https://buy.stripe.com/<id>` → `STRIPE_PRO_MONTHLY_URL`
- Pro Yearly: `https://buy.stripe.com/<id>` → `STRIPE_PRO_YEARLY_URL`
- Team Monthly: `https://buy.stripe.com/<id>` → `STRIPE_TEAM_MONTHLY_URL`
- Team Yearly: `https://buy.stripe.com/<id>` → `STRIPE_TEAM_YEARLY_URL`

Add to `.env.production`:
```
NEXT_PUBLIC_STRIPE_PRO_URL=https://buy.stripe.com/<pro-monthly-id>
NEXT_PUBLIC_STRIPE_TEAM_URL=https://buy.stripe.com/<team-monthly-id>
```

### 5. Run Database Migration

After deploying, run the new cloud_users migration:

```bash
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

Verify the table was created:
```bash
docker compose -f docker-compose.prod.yml exec pgvector \
  psql -U engramia engramia -c "\d cloud_users"
```

### 6. Deploy Dashboard

The dashboard lives in a separate repository: [engramia/dashboard](https://github.com/engramia/dashboard).
Its CI publishes Docker images to `ghcr.io/engramia/dashboard:<tag>`, which `docker-compose.prod.yml`
pulls via `IMAGE_TAG`.

```bash
# Pull the published image and (re)start the dashboard service
docker compose -f docker-compose.prod.yml pull dashboard
docker compose -f docker-compose.prod.yml up -d dashboard
```

See the dashboard repo for build instructions and local development.

### 7. Verify Registration Flow

1. Open https://app.engramia.dev/register
2. Register with email/password → should redirect to /setup
3. Verify tenant created:
   ```bash
   docker compose -f docker-compose.prod.yml exec pgvector \
     psql -U engramia engramia -c "SELECT id, slug, created_at FROM tenants ORDER BY created_at DESC LIMIT 3;"
   ```
4. Verify API key generated:
   ```bash
   docker compose -f docker-compose.prod.yml exec pgvector \
     psql -U engramia engramia -c "SELECT key_prefix, created_at FROM api_keys ORDER BY created_at DESC LIMIT 3;"
   ```
5. Test GitHub login → should work if GITHUB_CLIENT_ID is set
6. Test Google login → should work if GOOGLE_CLIENT_ID is set (and you're a test user while in Testing mode)

### 8. Environment Variables — Complete Reference for Registration

Add all of the following to `.env.production`:

```bash
# Auth.js
NEXTAUTH_URL=https://app.engramia.dev
NEXTAUTH_SECRET=<openssl rand -hex 32>

# GitHub OAuth
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=

# Google OAuth
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Stripe payment links (from Stripe Dashboard → Payment Links)
NEXT_PUBLIC_STRIPE_PRO_URL=
NEXT_PUBLIC_STRIPE_TEAM_URL=

# Backend JWT (used for /auth/* endpoints)
ENGRAMIA_JWT_PRIVATE_KEY=/secrets/private_key.pem
ENGRAMIA_JWT_PUBLIC_KEY=/secrets/public_key.pem
# Generate the key pair once with: engramia auth generate-keys --out-dir /secrets
# Legacy HS256 fallback (deprecated — see H-02):
# ENGRAMIA_JWT_SECRET=<openssl rand -hex 32>
```

### Common Issues

**"Callback URL mismatch" error from GitHub/Google**
→ The redirect URI in OAuth app settings must exactly match `https://app.engramia.dev/api/auth/callback/github` (or `/google`). Check for trailing slashes.

**Registration succeeds but API key not shown in setup wizard**
→ The API key is stored in `sessionStorage` from the register page. If the user navigates directly to `/setup`, it won't be there. They can find their key in Dashboard → Keys.

**Google: "Access blocked: This app's request is invalid"**
→ App is in Testing mode and the user's Google account isn't in the test users list. Add it in Google Cloud Console → OAuth consent screen → Test users.

**Users table doesn't exist (500 error on register)**
→ Run `alembic upgrade head` on the backend container.

---

## Apple Sign In (Optional)

Apple Sign In requires an Apple Developer Program membership ($99/year). Steps are documented separately when needed. For launch, GitHub + Google is sufficient.

To add Apple later:
1. Enroll in Apple Developer Program at https://developer.apple.com
2. Create an App ID with Sign In with Apple capability
3. Create a Service ID with the web domain `app.engramia.dev`
4. Generate a private key for Sign In with Apple
5. Add `Apple` provider to `src/auth.ts` in the [engramia/dashboard](https://github.com/engramia/dashboard) repo
6. Add env vars: `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_PRIVATE_KEY`, `APPLE_KEY_ID`
