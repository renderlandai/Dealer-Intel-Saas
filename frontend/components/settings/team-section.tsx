"use client";

import { useState, useEffect } from "react";
import {
  Users,
  UserPlus,
  Mail,
  Shield,
  Crown,
  Trash2,
  X,
  Clock,
  Send,
  CheckCircle,
  AlertCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  api,
  getTeamMembers,
  getTeamInvites,
  inviteTeamMember,
  cancelInvite,
  removeTeamMember,
} from "@/lib/api";

interface Member {
  id: string;
  user_id?: string;
  email: string;
  full_name?: string | null;
  role: string;
  joined_at?: string;
  created_at?: string;
}

interface Invite {
  id: string;
  email: string;
  role: string;
  status?: string;
  invited_by?: string;
  expires_at: string | null;
  created_at?: string;
}

const ROLE_ICONS: Record<string, React.ReactNode> = {
  owner: <Crown className="h-3.5 w-3.5 text-amber-400" />,
  admin: <Shield className="h-3.5 w-3.5 text-primary" />,
  member: <Users className="h-3.5 w-3.5 text-muted-foreground" />,
};

interface TeamSectionProps {
  maxSeats: number | null;
}

export function TeamSection({ maxSeats }: TeamSectionProps) {
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const [currentRole, setCurrentRole] = useState<string>("member");
  const isAdmin = currentRole === "owner" || currentRole === "admin";

  const refresh = async () => {
    try {
      const meResp = await api.get("/auth/me");
      const role = meResp.data?.role || "member";
      setCurrentRole(role);

      const [m, i] = await Promise.all([
        getTeamMembers(),
        role === "owner" || role === "admin" ? getTeamInvites() : Promise.resolve([]),
      ]);
      setMembers(m);
      setInvites(i);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const totalSeats = members.length + invites.length;
  const atLimit = maxSeats !== null && totalSeats >= maxSeats;

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    setSending(true);
    setFeedback(null);
    try {
      await inviteTeamMember(inviteEmail.trim(), inviteRole);
      setFeedback({ ok: true, msg: `Invite sent to ${inviteEmail.trim()}` });
      setInviteEmail("");
      refresh();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || "Failed to send invite";
      setFeedback({ ok: false, msg: detail });
    } finally {
      setSending(false);
      setTimeout(() => setFeedback(null), 5000);
    }
  };

  const handleCancelInvite = async (id: string) => {
    try {
      await cancelInvite(id);
      refresh();
    } catch {
      // handled by upgrade modal
    }
  };

  const handleRemoveMember = async (userId: string) => {
    if (!confirm("Remove this member from the organization?")) return;
    try {
      await removeTeamMember(userId);
      refresh();
    } catch {
      // handled by upgrade modal
    }
  };

  return (
    <Card className="opacity-0 animate-fade-up" style={{ animationFillMode: "forwards", animationDelay: "300ms" }}>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center bg-secondary border border-border">
            <Users className="h-5 w-5 text-muted-foreground" />
          </div>
          <div className="flex-1">
            <CardTitle className="text-base">Team</CardTitle>
            <CardDescription className="text-xs">
              Manage team members and invitations
              {maxSeats !== null && (
                <span className="ml-1 font-mono">
                  ({totalSeats}/{maxSeats} seats)
                </span>
              )}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {loading ? (
          <div className="space-y-2">
            <div className="h-12 bg-secondary/20 animate-pulse" />
            <div className="h-12 bg-secondary/20 animate-pulse" />
          </div>
        ) : (
          <>
            {/* Member list */}
            <div className="space-y-1">
              <p className="text-2xs uppercase tracking-wider text-muted-foreground mb-2">Members</p>
              {members.map((m) => (
                <div
                  key={m.user_id}
                  className="flex items-center gap-3 p-3 border border-border bg-secondary/20"
                >
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground flex-shrink-0">
                    {(m.email?.[0] || "U").toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">
                      {m.email || "Unknown user"}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    {ROLE_ICONS[m.role]}
                    <span className="capitalize">{m.role}</span>
                  </div>
                  {isAdmin && m.role !== "owner" && (
                    <button
                      onClick={() => handleRemoveMember(m.user_id || m.id)}
                      className="p-1 text-muted-foreground hover:text-destructive transition-colors"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>

            {/* Pending invites */}
            {isAdmin && invites.length > 0 && (
              <div className="space-y-1">
                <p className="text-2xs uppercase tracking-wider text-muted-foreground mb-2">
                  Pending Invites
                </p>
                {invites.map((inv) => (
                  <div
                    key={inv.id}
                    className="flex items-center gap-3 p-3 border border-dashed border-border"
                  >
                    <div className="flex h-8 w-8 items-center justify-center bg-secondary border border-border flex-shrink-0">
                      <Mail className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm truncate">{inv.email}</p>
                      <p className="text-2xs text-muted-foreground flex items-center gap-1 mt-0.5">
                        <Clock className="h-3 w-3" />
                        Expires {inv.expires_at ? new Date(inv.expires_at).toLocaleDateString() : "N/A"}
                      </p>
                    </div>
                    <span className="text-xs text-muted-foreground capitalize">{inv.role}</span>
                    <button
                      onClick={() => handleCancelInvite(inv.id)}
                      className="p-1 text-muted-foreground hover:text-destructive transition-colors"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Invite form */}
            {isAdmin && (
              <div className="space-y-3 pt-2 border-t border-border">
                <p className="text-2xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                  <UserPlus className="h-3.5 w-3.5" />
                  Invite New Member
                </p>
                <div className="flex gap-2">
                  <Input
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    placeholder="teammate@company.com"
                    className="flex-1"
                    disabled={atLimit || sending}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && inviteEmail.trim()) handleInvite();
                    }}
                  />
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value)}
                    className="h-10 px-3 bg-secondary border border-border text-sm"
                    disabled={atLimit || sending}
                  >
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                  </select>
                  <Button
                    onClick={handleInvite}
                    disabled={!inviteEmail.trim() || atLimit || sending}
                  >
                    <Send className="mr-1.5 h-4 w-4" />
                    {sending ? "Sending..." : "Invite"}
                  </Button>
                </div>

                {atLimit && (
                  <p className="text-xs text-amber-500">
                    You've reached your plan's seat limit ({maxSeats}). Upgrade to invite more members.
                  </p>
                )}

                {feedback && (
                  <div className={`flex items-center gap-2 text-sm ${
                    feedback.ok ? "text-success" : "text-destructive"
                  }`}>
                    {feedback.ok ? <CheckCircle className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
                    {feedback.msg}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
