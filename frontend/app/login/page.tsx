"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { Zap, Loader2, ArrowLeft } from "lucide-react";

export default function LoginPage() {
  const { signIn, signUp, resetPassword } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [isForgot, setIsForgot] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setLoading(true);

    if (isForgot) {
      const { error } = await resetPassword(email);
      if (error) {
        setError(error);
      } else {
        setSuccess("Password reset email sent. Check your inbox.");
      }
    } else if (isSignUp) {
      const { error } = await signUp(email, password);
      if (error) {
        setError(error);
      } else {
        setSuccess("Account created. Check your email to confirm, then sign in.");
        setIsSignUp(false);
      }
    } else {
      const { error } = await signIn(email, password);
      if (error) setError(error);
    }

    setLoading(false);
  };

  const switchMode = (mode: "login" | "signup" | "forgot") => {
    setError(null);
    setSuccess(null);
    setIsSignUp(mode === "signup");
    setIsForgot(mode === "forgot");
  };

  const title = isForgot
    ? "Reset your password"
    : isSignUp
    ? "Create your account"
    : "Sign in to your account";

  const buttonLabel = isForgot
    ? "Send Reset Link"
    : isSignUp
    ? "Create Account"
    : "Sign In";

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm space-y-8">
        <div className="text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center bg-primary">
            <Zap className="h-7 w-7 text-primary-foreground" />
          </div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">DEALER INTEL</h1>
          <p className="mt-1 text-sm text-muted-foreground">{title}</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="email" className="text-sm font-medium text-muted-foreground">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="you@company.com"
            />
          </div>

          {!isForgot && (
            <div className="space-y-1.5">
              <label htmlFor="password" className="text-sm font-medium text-muted-foreground">
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder="••••••••"
              />
            </div>
          )}

          {error && (
            <p className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2">
              {error}
            </p>
          )}

          {success && (
            <p className="text-sm text-green-400 bg-green-500/10 border border-green-500/20 rounded-md px-3 py-2">
              {success}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="flex h-10 w-full items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : buttonLabel}
          </button>
        </form>

        <div className="space-y-2 text-center">
          {isForgot ? (
            <button
              onClick={() => switchMode("login")}
              className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to sign in
            </button>
          ) : (
            <>
              {!isSignUp && (
                <button
                  onClick={() => switchMode("forgot")}
                  className="block w-full text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  Forgot your password?
                </button>
              )}
              <button
                onClick={() => switchMode(isSignUp ? "login" : "signup")}
                className="block w-full text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {isSignUp
                  ? "Already have an account? Sign in"
                  : "Need an account? Sign up"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
