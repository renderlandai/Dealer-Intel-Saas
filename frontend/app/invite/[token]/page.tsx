"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { CheckCircle, XCircle, Loader2, Users, LogIn } from "lucide-react";
import { BrandWordmark } from "@/components/ui/brand-wordmark";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { acceptInvite } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

type Status = "idle" | "accepting" | "accepted" | "error";

export default function AcceptInvitePage() {
  const params = useParams();
  const router = useRouter();
  const { user, loading } = useAuth();
  const token = params.token as string;

  const [status, setStatus] = useState<Status>("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const handleAccept = async () => {
    setStatus("accepting");
    setErrorMsg("");
    try {
      await acceptInvite(token);
      setStatus("accepted");
      setTimeout(() => {
        window.location.href = "/";
      }, 2000);
    } catch (err: any) {
      setStatus("error");
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 403) {
        setErrorMsg(detail || "This invite was sent to a different email address.");
      } else if (err?.response?.status === 410) {
        setErrorMsg("This invitation has expired. Ask your team admin for a new one.");
      } else if (err?.response?.status === 404) {
        setErrorMsg("Invitation not found. It may have already been used or canceled.");
      } else {
        setErrorMsg(detail || "Something went wrong. Please try again.");
      }
    }
  };

  const isAuthenticated = !loading && !!user;

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-background">
      <Card className="w-full max-w-md">
        <CardContent className="pt-8 pb-8 px-8">
          <div className="flex flex-col items-center text-center space-y-6">
            <BrandWordmark className="text-xl" />

            {loading ? (
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            ) : !isAuthenticated ? (
              <>
                <div className="flex h-16 w-16 items-center justify-center bg-primary/10 border border-primary/20 rounded-full">
                  <LogIn className="h-8 w-8 text-primary" />
                </div>
                <div>
                  <h1 className="text-xl font-semibold">Sign In Required</h1>
                  <p className="text-sm text-muted-foreground mt-2">
                    You need to sign in or create an account before you can accept this team invitation.
                  </p>
                </div>
                <div className="flex gap-3 w-full">
                  <Link href={`/login?redirect=/invite/${token}`} className={buttonVariants({ variant: "outline", className: "flex-1" })}>
                    Sign In
                  </Link>
                  <Link href={`/login?redirect=/invite/${token}&tab=signup`} className={buttonVariants({ className: "flex-1" })}>
                    Create Account
                  </Link>
                </div>
              </>
            ) : status === "accepted" ? (
              <>
                <div className="flex h-16 w-16 items-center justify-center bg-success/10 border border-success/20 rounded-full">
                  <CheckCircle className="h-8 w-8 text-success" />
                </div>
                <div>
                  <h1 className="text-xl font-semibold">You&apos;re In</h1>
                  <p className="text-sm text-muted-foreground mt-2">
                    You&apos;ve joined the organization. Redirecting to your dashboard...
                  </p>
                </div>
              </>
            ) : status === "error" ? (
              <>
                <div className="flex h-16 w-16 items-center justify-center bg-destructive/10 border border-destructive/20 rounded-full">
                  <XCircle className="h-8 w-8 text-destructive" />
                </div>
                <div>
                  <h1 className="text-xl font-semibold">Unable to Accept</h1>
                  <p className="text-sm text-muted-foreground mt-2">
                    {errorMsg}
                  </p>
                </div>
                <div className="flex gap-3 w-full">
                  <Button
                    variant="outline"
                    className="flex-1"
                    onClick={() => { setStatus("idle"); setErrorMsg(""); }}
                  >
                    Try Again
                  </Button>
                  <Button className="flex-1" onClick={() => router.push("/")}>
                    Go to Dashboard
                  </Button>
                </div>
              </>
            ) : (
              <>
                <div className="flex h-16 w-16 items-center justify-center bg-primary/10 border border-primary/20 rounded-full">
                  <Users className="h-8 w-8 text-primary" />
                </div>
                <div>
                  <h1 className="text-xl font-semibold">Team Invitation</h1>
                  <p className="text-sm text-muted-foreground mt-2">
                    You&apos;ve been invited to join an organization on Dealer Intel.
                    {user?.email && (
                      <span className="block mt-1 font-mono text-xs">
                        Signed in as {user.email}
                      </span>
                    )}
                  </p>
                </div>
                <Button
                  className="w-full h-12"
                  onClick={handleAccept}
                  disabled={status === "accepting"}
                >
                  {status === "accepting" ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Accepting...
                    </>
                  ) : (
                    <>
                      <CheckCircle className="mr-2 h-4 w-4" />
                      Accept Invitation
                    </>
                  )}
                </Button>
                <p className="text-xs text-muted-foreground">
                  By accepting, your account will be moved to the inviting organization.
                </p>
              </>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
