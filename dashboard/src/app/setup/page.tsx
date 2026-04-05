"use client"
import { useState, useEffect } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"

const PLANS = [
  {
    id: "sandbox",
    name: "Sandbox",
    price: "Free",
    description: "For development and testing",
    features: ["1 project", "10k patterns", "Community support"],
    cta: "Continue with Sandbox",
    highlight: false,
    stripeUrl: null as string | null,
  },
  {
    id: "pro",
    name: "Pro",
    price: "$29/mo",
    description: "For individual developers",
    features: ["5 projects", "500k patterns", "Priority support", "Eval analytics"],
    cta: "Start Pro Trial",
    highlight: true,
    stripeUrl: process.env.NEXT_PUBLIC_STRIPE_PRO_URL ?? null,
  },
  {
    id: "team",
    name: "Team",
    price: "$99/mo",
    description: "For teams and companies",
    features: ["Unlimited projects", "5M patterns", "RBAC", "SSO", "Dedicated support"],
    cta: "Start Team Trial",
    highlight: false,
    stripeUrl: process.env.NEXT_PUBLIC_STRIPE_TEAM_URL ?? null,
  },
]

export default function SetupPage() {
  const { data: session } = useSession()
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [apiKey, setApiKey] = useState("")
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const key = sessionStorage.getItem("engramia_new_api_key") ?? ""
    if (key) setApiKey(key)
  }, [])

  const handlePlanSelect = (plan: typeof PLANS[0]) => {
    if (plan.stripeUrl) {
      const email = encodeURIComponent(session?.user?.email ?? "")
      const tenant = encodeURIComponent((session as any)?.tenantId ?? "")
      window.location.href = `${plan.stripeUrl}?prefilled_email=${email}&client_reference_id=${tenant}`
    } else {
      setStep(3)
    }
  }

  const copy = () => {
    navigator.clipboard.writeText(apiKey)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-6">
      <div className="w-full max-w-3xl">
        {/* Progress */}
        <div className="flex items-center gap-2 mb-10 justify-center">
          {[1, 2, 3].map(s => (
            <div key={s} className="flex items-center gap-2">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${step >= s ? "bg-indigo-600 text-white" : "bg-gray-800 text-gray-500"}`}>{s}</div>
              {s < 3 && <div className={`w-12 h-0.5 ${step > s ? "bg-indigo-600" : "bg-gray-800"}`} />}
            </div>
          ))}
        </div>

        {/* Step 1: Welcome */}
        {step === 1 && (
          <div className="text-center">
            <div className="text-5xl mb-4">🧠</div>
            <h1 className="text-3xl font-bold text-white mb-2">Welcome to Engramia</h1>
            <p className="text-gray-400 mb-8">Your agents are about to get smarter. Let&apos;s get you set up in 2 minutes.</p>
            <button onClick={() => setStep(2)} className="px-8 py-3 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg font-medium text-lg transition">
              Get started →
            </button>
          </div>
        )}

        {/* Step 2: Plan selection */}
        {step === 2 && (
          <div>
            <h2 className="text-2xl font-bold text-white text-center mb-2">Choose your plan</h2>
            <p className="text-gray-400 text-center mb-8">You can upgrade or downgrade at any time</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {PLANS.map(plan => (
                <div key={plan.id} className={`p-6 rounded-xl border ${plan.highlight ? "border-indigo-500 bg-indigo-950/30" : "border-gray-800 bg-gray-900"}`}>
                  {plan.highlight && <div className="text-xs text-indigo-400 font-medium mb-2 uppercase tracking-wide">Most popular</div>}
                  <div className="text-xl font-bold text-white">{plan.name}</div>
                  <div className="text-2xl font-bold text-white mt-1 mb-1">{plan.price}</div>
                  <div className="text-sm text-gray-400 mb-4">{plan.description}</div>
                  <ul className="space-y-1 mb-6">
                    {plan.features.map(f => <li key={f} className="text-sm text-gray-300 flex gap-2"><span className="text-green-400">✓</span>{f}</li>)}
                  </ul>
                  <button onClick={() => handlePlanSelect(plan)}
                    className={`w-full py-2 rounded-lg font-medium transition text-sm ${plan.highlight ? "bg-indigo-600 hover:bg-indigo-500 text-white" : "bg-gray-800 hover:bg-gray-700 text-gray-200"}`}>
                    {plan.cta}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Step 3: API key + Quick Guide */}
        {step === 3 && (
          <div>
            <h2 className="text-2xl font-bold text-white text-center mb-2">You&apos;re all set! 🎉</h2>
            <p className="text-gray-400 text-center mb-8">Here&apos;s your API key — save it somewhere safe</p>

            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6">
              <div className="text-sm text-gray-400 mb-2">Your API key</div>
              <div className="flex items-center gap-3">
                <code className="flex-1 text-green-400 font-mono text-sm bg-gray-950 px-3 py-2 rounded-lg break-all">
                  {apiKey || "engramia-••••••••••••••••"}
                </code>
                <button onClick={copy} className="px-3 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg text-sm transition shrink-0">
                  {copied ? "Copied!" : "Copy"}
                </button>
              </div>
              <p className="text-xs text-gray-600 mt-2">This key won&apos;t be shown again. You can generate a new one in the Keys section.</p>
            </div>

            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6">
              <div className="text-sm text-gray-400 mb-3">Quick start</div>
              <pre className="text-sm text-gray-300 overflow-x-auto"><code>{`pip install engramia

from engramia import EngramiaClient

client = EngramiaClient(
    api_key="${apiKey || "YOUR_API_KEY"}",
    base_url="https://api.engramia.dev"
)

# Store what worked
client.learn("use_retry_logic", {"pattern": "retry 3x with backoff"}, eval_score=0.95)

# Recall later
results = client.recall("retry pattern")`}</code></pre>
            </div>

            <div className="flex gap-4 justify-center">
              <a href="https://engramia.dev/docs" className="px-6 py-2.5 border border-gray-700 text-gray-300 rounded-lg hover:border-gray-600 transition text-sm">
                Read the docs
              </a>
              <button onClick={() => router.push("/overview")} className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium transition">
                Go to Dashboard →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
