"use client";

import { useState, useEffect, useRef } from "react";
import Image from "next/image";
import {
  Upload,
  X,
  FileText,
  CheckCircle,
  ImageIcon,
  Building2,
  Save,
  Palette,
  Mail,
  Send,
  AlertCircle,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { getOrgSettings, updateOrgSettings, uploadOrgLogo, deleteOrgLogo, sendTestEmail } from "@/lib/api";

const COLOR_PRESETS = [
  { hex: "#334155", name: "Slate" },
  { hex: "#374151", name: "Graphite" },
  { hex: "#1f2937", name: "Charcoal" },
  { hex: "#475569", name: "Steel" },
  { hex: "#0d9488", name: "Teal" },
  { hex: "#166534", name: "Forest" },
  { hex: "#881337", name: "Burgundy" },
] as const;

const DEFAULT_COLOR = "#334155";

export default function SettingsPage() {
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [companyName, setCompanyName] = useState("");
  const [savedName, setSavedName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameSuccess, setNameSuccess] = useState(false);
  const [brandColor, setBrandColor] = useState(DEFAULT_COLOR);
  const [savedColor, setSavedColor] = useState(DEFAULT_COLOR);
  const [savingColor, setSavingColor] = useState(false);
  const [colorSuccess, setColorSuccess] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const [loading, setLoading] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [notifyEmail, setNotifyEmail] = useState("");
  const [savedEmail, setSavedEmail] = useState("");
  const [notifyOn, setNotifyOn] = useState(true);
  const [savingNotify, setSavingNotify] = useState(false);
  const [notifySuccess, setNotifySuccess] = useState(false);
  const [sendingTest, setSendingTest] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);

  useEffect(() => {
    getOrgSettings()
      .then((res) => {
        setLogoUrl(res.logo_url || null);
        setCompanyName(res.name || "");
        setSavedName(res.name || "");
        const color = res.report_brand_color || DEFAULT_COLOR;
        setBrandColor(color);
        setSavedColor(color);
        setNotifyEmail(res.notify_email || "");
        setSavedEmail(res.notify_email || "");
        setNotifyOn(res.notify_on_violation ?? true);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSaveName = async () => {
    const trimmed = companyName.trim();
    if (!trimmed || trimmed === savedName) return;
    setSavingName(true);
    setNameSuccess(false);
    try {
      await updateOrgSettings({ name: trimmed });
      setSavedName(trimmed);
      setNameSuccess(true);
      setTimeout(() => setNameSuccess(false), 3000);
    } catch (error) {
      console.error("Failed to update company name:", error);
    } finally {
      setSavingName(false);
    }
  };

  const handleSelectColor = async (hex: string) => {
    setBrandColor(hex);
    setSavingColor(true);
    setColorSuccess(false);
    try {
      await updateOrgSettings({ report_brand_color: hex });
      setSavedColor(hex);
      setColorSuccess(true);
      setTimeout(() => setColorSuccess(false), 3000);
    } catch (error) {
      console.error("Failed to update brand color:", error);
      setBrandColor(savedColor);
    } finally {
      setSavingColor(false);
    }
  };

  const nameChanged = companyName.trim() !== savedName;

  const handleSaveNotify = async () => {
    setSavingNotify(true);
    setNotifySuccess(false);
    setTestResult(null);
    try {
      await updateOrgSettings({
        notify_email: notifyEmail.trim(),
        notify_on_violation: notifyOn,
      });
      setSavedEmail(notifyEmail.trim());
      setNotifySuccess(true);
      setTimeout(() => setNotifySuccess(false), 3000);
    } catch (error) {
      console.error("Failed to save notification settings:", error);
    } finally {
      setSavingNotify(false);
    }
  };

  const handleToggleNotify = async (enabled: boolean) => {
    setNotifyOn(enabled);
    try {
      await updateOrgSettings({ notify_on_violation: enabled });
    } catch (error) {
      console.error("Failed to toggle notifications:", error);
      setNotifyOn(!enabled);
    }
  };

  const handleTestEmail = async () => {
    setSendingTest(true);
    setTestResult(null);
    try {
      const result = await sendTestEmail();
      setTestResult({ ok: true, msg: result.message });
    } catch (error: any) {
      const detail = error?.response?.data?.detail || "Failed to send test email";
      setTestResult({ ok: false, msg: detail });
    } finally {
      setSendingTest(false);
    }
  };

  const emailChanged = notifyEmail.trim() !== savedEmail;

  const handleUpload = async (file: File) => {
    setUploading(true);
    setUploadSuccess(false);
    try {
      const result = await uploadOrgLogo(file);
      setLogoUrl(result.logo_url);
      setUploadSuccess(true);
      setTimeout(() => setUploadSuccess(false), 3000);
    } catch (error) {
      console.error("Logo upload failed:", error);
    } finally {
      setUploading(false);
    }
  };

  const handleRemove = async () => {
    try {
      await deleteOrgLogo();
      setLogoUrl(null);
    } catch (error) {
      console.error("Logo remove failed:", error);
    }
  };

  return (
    <div className="min-h-screen">
      <Header
        title="Settings"
        description="Organization configuration and preferences"
      />

      <div className="p-8 max-w-3xl space-y-6">
        {/* Company Info */}
        <Card className="opacity-0 animate-fade-up" style={{ animationFillMode: "forwards" }}>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center bg-secondary border border-border">
                <Building2 className="h-5 w-5 text-muted-foreground" />
              </div>
              <div>
                <CardTitle className="text-base">Company Info</CardTitle>
                <CardDescription className="text-xs">
                  Your organization name used across reports and the platform
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-2xs uppercase tracking-wider text-muted-foreground mb-3">Company Name</p>
              {loading ? (
                <div className="h-10 border border-border bg-secondary/20 animate-pulse" />
              ) : (
                <div className="flex gap-3">
                  <Input
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    placeholder="Enter company name"
                    className="flex-1"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && nameChanged) handleSaveName();
                    }}
                  />
                  <Button
                    onClick={handleSaveName}
                    disabled={!nameChanged || savingName}
                    size="default"
                  >
                    <Save className="mr-1.5 h-4 w-4" />
                    {savingName ? "Saving..." : "Save"}
                  </Button>
                </div>
              )}
              {nameSuccess && (
                <div className="flex items-center gap-2 mt-3 text-success opacity-0 animate-fade-up" style={{ animationFillMode: "forwards" }}>
                  <CheckCircle className="h-4 w-4" />
                  <span className="text-sm">Company name updated</span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Email Notifications */}
        <Card className="opacity-0 animate-fade-up" style={{ animationFillMode: "forwards", animationDelay: "75ms" }}>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center bg-secondary border border-border">
                <Mail className="h-5 w-5 text-muted-foreground" />
              </div>
              <div className="flex-1">
                <CardTitle className="text-base">Email Notifications</CardTitle>
                <CardDescription className="text-xs">
                  Receive scan summaries and violation alerts by email
                </CardDescription>
              </div>
              <button
                onClick={() => handleToggleNotify(!notifyOn)}
                className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ${
                  notifyOn ? "bg-primary" : "bg-muted"
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                    notifyOn ? "translate-x-5" : "translate-x-0"
                  }`}
                />
              </button>
            </div>
          </CardHeader>
          {notifyOn && (
            <CardContent className="space-y-4">
              {loading ? (
                <div className="h-10 border border-border bg-secondary/20 animate-pulse" />
              ) : (
                <>
                  <div className="flex gap-3">
                    <Input
                      type="email"
                      value={notifyEmail}
                      onChange={(e) => setNotifyEmail(e.target.value)}
                      placeholder="alerts@yourcompany.com"
                      className="flex-1"
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && emailChanged && notifyEmail.trim()) handleSaveNotify();
                      }}
                    />
                    <Button
                      onClick={handleSaveNotify}
                      disabled={!emailChanged || !notifyEmail.trim() || savingNotify}
                      size="default"
                    >
                      <Save className="mr-1.5 h-4 w-4" />
                      {savingNotify ? "Saving..." : "Save"}
                    </Button>
                    <Button
                      variant="outline"
                      onClick={handleTestEmail}
                      disabled={sendingTest || !savedEmail}
                    >
                      <Send className="mr-1.5 h-4 w-4" />
                      {sendingTest ? "Sending..." : "Test"}
                    </Button>
                  </div>

                  {notifySuccess && (
                    <div className="flex items-center gap-2 text-success opacity-0 animate-fade-up" style={{ animationFillMode: "forwards" }}>
                      <CheckCircle className="h-4 w-4" />
                      <span className="text-sm">Notification email saved</span>
                    </div>
                  )}
                  {testResult && (
                    <div className={`flex items-center gap-2 ${testResult.ok ? "text-success" : "text-destructive"}`}>
                      {testResult.ok ? <CheckCircle className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
                      <span className="text-sm">{testResult.msg}</span>
                    </div>
                  )}

                  <p className="text-2xs text-muted-foreground">
                    You will receive an email after each scan completes with a summary of results and any violations found.
                  </p>
                </>
              )}
            </CardContent>
          )}
        </Card>

        {/* Report Theme */}
        <Card className="opacity-0 animate-fade-up" style={{ animationFillMode: "forwards", animationDelay: "150ms" }}>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center bg-secondary border border-border">
                <Palette className="h-5 w-5 text-muted-foreground" />
              </div>
              <div>
                <CardTitle className="text-base">Report Theme</CardTitle>
                <CardDescription className="text-xs">
                  Choose the accent color for PDF report headers, tables, and section titles
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-2xs uppercase tracking-wider text-muted-foreground mb-3">Accent Color</p>
              {loading ? (
                <div className="h-12 border border-border bg-secondary/20 animate-pulse" />
              ) : (
                <div className="flex flex-wrap gap-3">
                  {COLOR_PRESETS.map((preset) => (
                    <button
                      key={preset.hex}
                      onClick={() => handleSelectColor(preset.hex)}
                      disabled={savingColor}
                      className="group flex flex-col items-center gap-1.5"
                    >
                      <div
                        className={`h-10 w-10 rounded-full border-2 transition-all ${
                          brandColor === preset.hex
                            ? "border-foreground scale-110 ring-2 ring-foreground/20"
                            : "border-transparent hover:border-border hover:scale-105"
                        }`}
                        style={{ backgroundColor: preset.hex }}
                      />
                      <span className={`text-2xs transition-colors ${
                        brandColor === preset.hex
                          ? "text-foreground font-medium"
                          : "text-muted-foreground"
                      }`}>
                        {preset.name}
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {colorSuccess && (
                <div className="flex items-center gap-2 mt-3 text-success opacity-0 animate-fade-up" style={{ animationFillMode: "forwards" }}>
                  <CheckCircle className="h-4 w-4" />
                  <span className="text-sm">Report theme updated</span>
                </div>
              )}
            </div>

            {/* Preview strip */}
            <div className="border border-border overflow-hidden">
              <div className="h-2" style={{ backgroundColor: brandColor }} />
              <div className="p-3 flex items-center gap-3">
                <div className="h-6 w-20 rounded-sm" style={{ backgroundColor: brandColor }} />
                <div className="flex-1 space-y-1.5">
                  <div className="h-2 w-32 rounded-full bg-muted" />
                  <div className="h-2 w-24 rounded-full bg-muted/60" />
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Report Branding */}
        <Card className="opacity-0 animate-fade-up" style={{ animationFillMode: "forwards", animationDelay: "225ms" }}>
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center bg-secondary border border-border">
                <FileText className="h-5 w-5 text-muted-foreground" />
              </div>
              <div>
                <CardTitle className="text-base">Report Branding</CardTitle>
                <CardDescription className="text-xs">
                  Customize the logo that appears in exported PDF compliance reports
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* Current Logo Preview */}
            <div>
              <p className="text-2xs uppercase tracking-wider text-muted-foreground mb-3">Current Logo</p>
              {loading ? (
                <div className="h-20 border border-border bg-secondary/20 animate-pulse flex items-center justify-center">
                  <span className="text-xs text-muted-foreground">Loading...</span>
                </div>
              ) : logoUrl ? (
                <div className="border border-border bg-secondary/20 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="relative h-14 w-44 flex-shrink-0">
                      <Image
                        src={logoUrl}
                        alt="Report logo"
                        fill
                        className="object-contain object-left"
                        unoptimized
                      />
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:text-destructive hover:border-destructive/50 flex-shrink-0"
                      onClick={handleRemove}
                    >
                      <X className="mr-1.5 h-3.5 w-3.5" />
                      Remove
                    </Button>
                  </div>
                  <p className="text-2xs text-muted-foreground mt-3">
                    This logo will appear in the header of all PDF reports.
                  </p>
                </div>
              ) : (
                <div className="border border-dashed border-border p-4 flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center bg-secondary/50 border border-border flex-shrink-0">
                    <ImageIcon className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">No custom logo uploaded</p>
                    <p className="text-2xs text-muted-foreground mt-0.5">
                      Reports will use the default Dealer Intel branding
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Upload Area */}
            <div>
              <p className="text-2xs uppercase tracking-wider text-muted-foreground mb-3">
                {logoUrl ? "Replace Logo" : "Upload Logo"}
              </p>
              <label className="relative block cursor-pointer">
                <div className="border-2 border-dashed border-border hover:border-primary/50 transition-colors p-6 text-center">
                  <Upload className="h-8 w-8 mx-auto text-muted-foreground mb-3" />
                  <p className="text-sm font-medium">
                    {uploading ? "Uploading..." : "Click to select an image"}
                  </p>
                  <p className="text-2xs text-muted-foreground mt-1">
                    PNG, JPEG, or WebP — max 2 MB
                  </p>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="absolute inset-0 opacity-0 cursor-pointer"
                  disabled={uploading}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      handleUpload(file);
                      e.target.value = "";
                    }
                  }}
                />
              </label>

              {uploadSuccess && (
                <div className="flex items-center gap-2 mt-3 text-success opacity-0 animate-fade-up" style={{ animationFillMode: "forwards" }}>
                  <CheckCircle className="h-4 w-4" />
                  <span className="text-sm">Logo updated — it will appear on your next PDF report</span>
                </div>
              )}
            </div>

            {/* Tips */}
            <div className="border border-border bg-secondary/20 p-4">
              <p className="text-2xs uppercase tracking-wider text-muted-foreground mb-2">Tips</p>
              <ul className="text-xs text-muted-foreground space-y-1.5">
                <li>• Use a horizontal/landscape logo for best results in the PDF header</li>
                <li>• Transparent PNG backgrounds work well on the white report</li>
                <li>• Recommended size: 400×100 pixels or similar aspect ratio</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
