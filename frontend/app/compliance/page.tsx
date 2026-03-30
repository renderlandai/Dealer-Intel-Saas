"use client";

import { useState } from "react";
import {
  Plus,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  Calendar,
  Pencil,
  Trash2,
  X,
  Power,
  PowerOff,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  useComplianceRules,
  useCreateComplianceRule,
  useUpdateComplianceRule,
  useDeleteComplianceRule,
} from "@/lib/hooks";
import type { ComplianceRule, RuleType, RuleSeverity } from "@/lib/api";

const RULE_TYPE_META: Record<RuleType, { label: string; description: string; icon: typeof ShieldCheck }> = {
  required_element: {
    label: "Required Element",
    description: "Ensure specific elements are present in distributor creatives",
    icon: ShieldCheck,
  },
  forbidden_element: {
    label: "Forbidden Element",
    description: "Flag creatives containing prohibited elements",
    icon: ShieldX,
  },
  date_check: {
    label: "Date Check",
    description: "Verify creatives are within valid date ranges",
    icon: Calendar,
  },
};

const SEVERITY_STYLES: Record<RuleSeverity, string> = {
  info: "border-blue-500/30 bg-blue-500/10 text-blue-400",
  warning: "border-yellow-500/30 bg-yellow-500/10 text-yellow-400",
  critical: "border-destructive/30 bg-destructive/10 text-destructive",
};

const EMPTY_FORM = {
  name: "",
  description: "",
  rule_type: "required_element" as RuleType,
  rule_config: {} as Record<string, unknown>,
  severity: "warning" as RuleSeverity,
};

function RuleConfigFields({
  ruleType,
  config,
  onChange,
}: {
  ruleType: RuleType;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}) {
  if (ruleType === "required_element") {
    return (
      <div className="space-y-3">
        <div>
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Required Element
          </label>
          <Input
            placeholder="e.g., brand logo, disclaimer text, phone number"
            value={(config.element as string) || ""}
            onChange={(e) => onChange({ ...config, element: e.target.value })}
            className="mt-2"
          />
        </div>
        <div>
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Location Hint (optional)
          </label>
          <Input
            placeholder="e.g., bottom-right corner, footer area"
            value={(config.location as string) || ""}
            onChange={(e) => onChange({ ...config, location: e.target.value })}
            className="mt-2"
          />
        </div>
      </div>
    );
  }

  if (ruleType === "forbidden_element") {
    return (
      <div className="space-y-3">
        <div>
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Forbidden Element
          </label>
          <Input
            placeholder="e.g., competitor logo, outdated pricing, expired promo"
            value={(config.element as string) || ""}
            onChange={(e) => onChange({ ...config, element: e.target.value })}
            className="mt-2"
          />
        </div>
        <div>
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Reason (optional)
          </label>
          <Input
            placeholder="e.g., violates brand guidelines section 4.2"
            value={(config.reason as string) || ""}
            onChange={(e) => onChange({ ...config, reason: e.target.value })}
            className="mt-2"
          />
        </div>
      </div>
    );
  }

  if (ruleType === "date_check") {
    return (
      <div className="space-y-3">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Valid From
            </label>
            <Input
              type="date"
              value={(config.valid_from as string) || ""}
              onChange={(e) => onChange({ ...config, valid_from: e.target.value })}
              className="mt-2"
            />
          </div>
          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Valid Until
            </label>
            <Input
              type="date"
              value={(config.valid_until as string) || ""}
              onChange={(e) => onChange({ ...config, valid_until: e.target.value })}
              className="mt-2"
            />
          </div>
        </div>
        <div>
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Date Field to Check (optional)
          </label>
          <Input
            placeholder="e.g., promotion end date, offer expiry"
            value={(config.date_field as string) || ""}
            onChange={(e) => onChange({ ...config, date_field: e.target.value })}
            className="mt-2"
          />
        </div>
      </div>
    );
  }

  return null;
}

export default function CompliancePage() {
  const { data: rules = [], isLoading, isError, refetch } = useComplianceRules();
  const createMutation = useCreateComplianceRule();
  const updateMutation = useUpdateComplianceRule();
  const deleteMutation = useDeleteComplianceRule();

  const [showCreate, setShowCreate] = useState(false);
  const [editingRule, setEditingRule] = useState<ComplianceRule | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);

  const handleCreate = async () => {
    if (!form.name.trim()) {
      alert("Rule name is required.");
      return;
    }
    try {
      await createMutation.mutateAsync({
        name: form.name,
        description: form.description || undefined,
        rule_type: form.rule_type,
        rule_config: form.rule_config,
        severity: form.severity,
      });
      setShowCreate(false);
      setForm(EMPTY_FORM);
    } catch (error: any) {
      alert(error?.response?.data?.detail || "Failed to create rule.");
    }
  };

  const handleStartEdit = (rule: ComplianceRule, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingRule(rule);
    setForm({
      name: rule.name,
      description: rule.description || "",
      rule_type: rule.rule_type,
      rule_config: rule.rule_config,
      severity: rule.severity,
    });
  };

  const handleSaveEdit = async () => {
    if (!editingRule || !form.name.trim()) return;
    try {
      await updateMutation.mutateAsync({
        id: editingRule.id,
        updates: {
          name: form.name,
          description: form.description || undefined,
          rule_type: form.rule_type,
          rule_config: form.rule_config,
          severity: form.severity,
        },
      });
      setEditingRule(null);
      setForm(EMPTY_FORM);
    } catch (error: any) {
      alert(error?.response?.data?.detail || "Failed to update rule.");
    }
  };

  const handleToggleActive = async (rule: ComplianceRule, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await updateMutation.mutateAsync({
        id: rule.id,
        updates: { is_active: !rule.is_active },
      });
    } catch (error: any) {
      alert(error?.response?.data?.detail || "Failed to update rule.");
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteMutation.mutateAsync(id);
      setDeleteConfirm(null);
    } catch (error: any) {
      alert(error?.response?.data?.detail || "Failed to delete rule.");
    }
  };

  const activeCount = rules.filter((r: ComplianceRule) => r.is_active).length;

  return (
    <div className="min-h-screen">
      <Header
        title="Compliance Rules"
        description="Define rules that are checked during AI analysis of distributor creatives"
      />

      <div className="p-8 space-y-6">
        {/* Summary + Actions */}
        <div className="flex justify-between items-center opacity-0 animate-fade-up">
          <div className="flex items-center gap-4">
            <p className="text-sm text-muted-foreground font-mono">
              {rules.length} rule{rules.length !== 1 ? "s" : ""}
            </p>
            {rules.length > 0 && (
              <Badge className="border-success/30 bg-success/10 text-success font-mono">
                {activeCount} active
              </Badge>
            )}
          </div>
          <Button onClick={() => { setShowCreate(true); setForm(EMPTY_FORM); }} size="sm">
            <Plus className="mr-2 h-4 w-4" />
            Add Rule
          </Button>
        </div>

        {/* Create Form */}
        {showCreate && (
          <Card className="border-primary/30 opacity-0 animate-fade-up">
            <CardHeader className="border-b border-border flex flex-row items-center justify-between">
              <CardTitle className="text-base">New Compliance Rule</CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setShowCreate(false)} className="h-8 w-8 p-0">
                <X className="h-4 w-4" />
              </Button>
            </CardHeader>
            <CardContent className="pt-5 space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="md:col-span-2">
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Rule Name *
                  </label>
                  <Input
                    placeholder="e.g., Brand Logo Required"
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    className="mt-2"
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Description
                  </label>
                  <Input
                    placeholder="What does this rule check for?"
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    className="mt-2"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Rule Type *
                  </label>
                  <select
                    value={form.rule_type}
                    onChange={(e) => setForm({ ...form, rule_type: e.target.value as RuleType, rule_config: {} })}
                    className="mt-2 flex h-10 w-full border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {Object.entries(RULE_TYPE_META).map(([key, meta]) => (
                      <option key={key} value={key}>{meta.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Severity *
                  </label>
                  <select
                    value={form.severity}
                    onChange={(e) => setForm({ ...form, severity: e.target.value as RuleSeverity })}
                    className="mt-2 flex h-10 w-full border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <option value="info">Info</option>
                    <option value="warning">Warning</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
              </div>

              <div className="pt-2 border-t border-border">
                <p className="text-xs text-muted-foreground mb-3">
                  {RULE_TYPE_META[form.rule_type].description}
                </p>
                <RuleConfigFields
                  ruleType={form.rule_type}
                  config={form.rule_config}
                  onChange={(config) => setForm({ ...form, rule_config: config })}
                />
              </div>

              <div className="flex gap-2 pt-2">
                <Button onClick={handleCreate} disabled={createMutation.isPending} size="sm">
                  {createMutation.isPending ? "Creating..." : "Create Rule"}
                </Button>
                <Button variant="outline" onClick={() => setShowCreate(false)} size="sm">
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Edit Modal */}
        {editingRule && (
          <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-2xl border-primary/30 animate-fade-up">
              <CardHeader className="border-b border-border flex flex-row items-center justify-between">
                <CardTitle className="text-base">Edit Compliance Rule</CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => { setEditingRule(null); setForm(EMPTY_FORM); }}
                  className="h-8 w-8 p-0"
                >
                  <X className="h-4 w-4" />
                </Button>
              </CardHeader>
              <CardContent className="pt-5 space-y-4">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="md:col-span-2">
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Rule Name *
                    </label>
                    <Input
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Description
                    </label>
                    <Input
                      value={form.description}
                      onChange={(e) => setForm({ ...form, description: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Rule Type
                    </label>
                    <select
                      value={form.rule_type}
                      onChange={(e) => setForm({ ...form, rule_type: e.target.value as RuleType, rule_config: {} })}
                      className="mt-2 flex h-10 w-full border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {Object.entries(RULE_TYPE_META).map(([key, meta]) => (
                        <option key={key} value={key}>{meta.label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Severity
                    </label>
                    <select
                      value={form.severity}
                      onChange={(e) => setForm({ ...form, severity: e.target.value as RuleSeverity })}
                      className="mt-2 flex h-10 w-full border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <option value="info">Info</option>
                      <option value="warning">Warning</option>
                      <option value="critical">Critical</option>
                    </select>
                  </div>
                </div>

                <div className="pt-2 border-t border-border">
                  <p className="text-xs text-muted-foreground mb-3">
                    {RULE_TYPE_META[form.rule_type].description}
                  </p>
                  <RuleConfigFields
                    ruleType={form.rule_type}
                    config={form.rule_config}
                    onChange={(config) => setForm({ ...form, rule_config: config })}
                  />
                </div>

                <div className="flex gap-2 pt-4 border-t border-border">
                  <Button onClick={handleSaveEdit} disabled={updateMutation.isPending} size="sm">
                    {updateMutation.isPending ? "Saving..." : "Save Changes"}
                  </Button>
                  <Button variant="outline" onClick={() => { setEditingRule(null); setForm(EMPTY_FORM); }} size="sm">
                    Cancel
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Rules List */}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="stat-card animate-pulse">
                <div className="flex items-center gap-4">
                  <div className="h-12 w-12 bg-secondary" />
                  <div className="flex-1">
                    <div className="h-5 bg-secondary w-1/4 mb-2" />
                    <div className="h-4 bg-secondary w-1/3" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : isError ? (
          <Card className="opacity-0 animate-fade-up border-destructive/30">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <div className="h-14 w-14 flex items-center justify-center bg-destructive/10 border border-destructive/20 mb-4">
                <ShieldAlert className="h-7 w-7 text-destructive" />
              </div>
              <h3 className="text-base font-medium">Failed to load compliance rules</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-md text-center">
                Could not connect to the server. Make sure the backend is running.
              </p>
              <Button className="mt-6" onClick={() => refetch()} size="sm" variant="outline">
                Try Again
              </Button>
            </CardContent>
          </Card>
        ) : rules.length === 0 ? (
          <Card className="opacity-0 animate-fade-up">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <div className="h-14 w-14 flex items-center justify-center bg-secondary border border-border mb-4">
                <ShieldCheck className="h-7 w-7 text-muted-foreground" />
              </div>
              <h3 className="text-base font-medium">No compliance rules yet</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-md text-center">
                Create rules to automatically check distributor creatives for brand compliance during scans
              </p>
              <Button className="mt-6" onClick={() => { setShowCreate(true); setForm(EMPTY_FORM); }} size="sm">
                <Plus className="mr-2 h-4 w-4" />
                Create First Rule
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {rules.map((rule: ComplianceRule, index: number) => {
              const meta = RULE_TYPE_META[rule.rule_type] || RULE_TYPE_META.required_element;
              const Icon = meta.icon;

              return (
                <div
                  key={rule.id}
                  className="stat-card transition-all hover:border-primary/30 group opacity-0 animate-fade-up"
                  style={{ animationDelay: `${index * 50}ms`, animationFillMode: "forwards" }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div className={`flex h-12 w-12 items-center justify-center border ${
                        rule.is_active
                          ? "bg-primary/10 border-primary/20"
                          : "bg-secondary border-border"
                      }`}>
                        <Icon className={`h-5 w-5 ${rule.is_active ? "text-primary" : "text-muted-foreground"}`} />
                      </div>
                      <div>
                        <div className="flex items-center gap-3">
                          <h3 className={`font-medium ${!rule.is_active ? "text-muted-foreground" : ""}`}>
                            {rule.name}
                          </h3>
                          <Badge className={SEVERITY_STYLES[rule.severity]}>
                            {rule.severity}
                          </Badge>
                          {!rule.is_active && (
                            <Badge className="border-border bg-secondary text-muted-foreground">
                              disabled
                            </Badge>
                          )}
                        </div>
                        <div className="flex items-center gap-4 mt-1.5 text-xs text-muted-foreground">
                          <span>{meta.label}</span>
                          {rule.description && (
                            <>
                              <span className="text-border">·</span>
                              <span className="truncate max-w-md">{rule.description}</span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => handleToggleActive(rule, e)}
                        title={rule.is_active ? "Disable rule" : "Enable rule"}
                        className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        {rule.is_active ? (
                          <PowerOff className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <Power className="h-4 w-4 text-success" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => handleStartEdit(rule, e)}
                        className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      {deleteConfirm === rule.id ? (
                        <div className="flex items-center gap-1">
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => handleDelete(rule.id)}
                            disabled={deleteMutation.isPending}
                            className="h-8 text-xs"
                          >
                            Confirm
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDeleteConfirm(null)}
                            className="h-8 w-8 p-0"
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => { e.stopPropagation(); setDeleteConfirm(rule.id); }}
                          className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  </div>

                  {/* Config preview */}
                  {Object.keys(rule.rule_config).length > 0 && (
                    <div className="mt-3 pt-3 border-t border-border/50">
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(rule.rule_config).map(([key, value]) =>
                          value ? (
                            <span
                              key={key}
                              className="inline-flex items-center px-2 py-1 bg-secondary/50 border border-border text-2xs font-mono text-muted-foreground"
                            >
                              {key}: {String(value)}
                            </span>
                          ) : null
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
