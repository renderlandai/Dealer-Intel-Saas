"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Plus,
  Building2,
  Globe,
  Facebook,
  Instagram,
  Youtube,
  MapPin,
  ArrowRight,
  Pencil,
  X,
  Upload,
  Download,
  FileSpreadsheet,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  useDistributors,
  useCreateDistributor,
  useUpdateDistributor,
  useBulkCreateDistributors,
} from "@/lib/hooks";
import {
  distributorCreateSchema,
  distributorUpdateSchema,
  distributorCsvRowSchema,
} from "@/lib/schemas";
import { parseCsvWithHeaders } from "@/lib/csv";
import type { DistributorCreate } from "@/lib/api";

interface Distributor {
  id: string;
  name: string;
  code: string | null;
  website_url: string | null;
  facebook_url: string | null;
  instagram_url: string | null;
  youtube_url: string | null;
  google_ads_advertiser_id: string | null;
  region: string | null;
  status: string;
  match_count: number;
}

type CsvParsedRow = {
  rowNumber: number;
  raw: Record<string, string>;
  data: DistributorCreate | null;
  errors: string[];
};

const REQUIRED_HEADERS = ["name"] as const;
const RECOGNIZED_HEADERS = [
  "name",
  "code",
  "region",
  "website_url",
  "facebook_url",
  "instagram_url",
  "youtube_url",
  "google_ads_advertiser_id",
  "status",
] as const;
const MAX_CSV_ROWS = 1000;
const BULK_CHUNK_SIZE = 50;

export default function DistributorsPage() {
  const { data: distributors = [], isLoading: loading, isError, refetch } = useDistributors();
  const createDistributorMutation = useCreateDistributor();
  const updateDistributorMutation = useUpdateDistributor();
  const bulkCreateMutation = useBulkCreateDistributors();
  const [showCreate, setShowCreate] = useState(false);
  const [editingDistributor, setEditingDistributor] = useState<Distributor | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [importFileName, setImportFileName] = useState<string>("");
  const [importHeaders, setImportHeaders] = useState<string[]>([]);
  const [importRows, setImportRows] = useState<CsvParsedRow[]>([]);
  const [importError, setImportError] = useState<string>("");
  const [importResult, setImportResult] = useState<{
    inserted: number;
    failed: number;
    message: string;
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const existingNames = useMemo(
    () => new Set(distributors.map((d: Distributor) => d.name.trim().toLowerCase())),
    [distributors],
  );

  const validRows = importRows.filter((r) => r.errors.length === 0);
  const invalidRows = importRows.filter((r) => r.errors.length > 0);
  const duplicateRows = validRows.filter((r) =>
    r.data ? existingNames.has(r.data.name.trim().toLowerCase()) : false,
  );
  const importableRows = validRows.filter(
    (r) => r.data && !existingNames.has(r.data.name.trim().toLowerCase()),
  );

  const resetImportState = () => {
    setImportFileName("");
    setImportHeaders([]);
    setImportRows([]);
    setImportError("");
    setImportResult(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleCloseImport = () => {
    setShowImport(false);
    resetImportState();
  };

  const handleFilePicked = async (file: File) => {
    resetImportState();
    setImportFileName(file.name);

    let text: string;
    try {
      text = await file.text();
    } catch (err) {
      setImportError("Could not read file.");
      return;
    }

    let parsed;
    try {
      parsed = parseCsvWithHeaders(text);
    } catch (err) {
      setImportError("Could not parse CSV. Make sure it's valid comma-separated data.");
      return;
    }

    if (parsed.rows.length === 0) {
      setImportError("CSV has no data rows.");
      return;
    }
    if (parsed.rows.length > MAX_CSV_ROWS) {
      setImportError(`Too many rows (${parsed.rows.length}). Max ${MAX_CSV_ROWS} per import.`);
      return;
    }

    const missing = REQUIRED_HEADERS.filter((h) => !parsed.headers.includes(h));
    if (missing.length > 0) {
      setImportError(
        `Missing required column(s): ${missing.join(", ")}. ` +
          `Recognized columns: ${RECOGNIZED_HEADERS.join(", ")}.`,
      );
      setImportHeaders(parsed.headers);
      return;
    }

    setImportHeaders(parsed.headers);

    const seenNames = new Set<string>();
    const validated: CsvParsedRow[] = parsed.rows.map((raw, idx) => {
      const rowNumber = idx + 2; // +1 for header, +1 to be 1-indexed
      const parsedRow = distributorCsvRowSchema.safeParse(raw);
      const errors: string[] = [];

      if (!parsedRow.success) {
        for (const issue of parsedRow.error.issues) {
          const field = issue.path.join(".") || "row";
          errors.push(`${field}: ${issue.message}`);
        }
        return { rowNumber, raw, data: null, errors };
      }

      const row = parsedRow.data;
      const nameKey = row.name.trim().toLowerCase();
      if (seenNames.has(nameKey)) {
        errors.push("Duplicate name within this CSV");
      } else {
        seenNames.add(nameKey);
      }

      const data: DistributorCreate = {
        name: row.name.trim(),
        ...(row.code ? { code: row.code } : {}),
        ...(row.region ? { region: row.region } : {}),
        ...(row.website_url ? { website_url: row.website_url } : {}),
        ...(row.facebook_url ? { facebook_url: row.facebook_url } : {}),
        ...(row.instagram_url ? { instagram_url: row.instagram_url } : {}),
        ...(row.youtube_url ? { youtube_url: row.youtube_url } : {}),
        ...(row.google_ads_advertiser_id
          ? { google_ads_advertiser_id: row.google_ads_advertiser_id }
          : {}),
        status: row.status,
      };

      return { rowNumber, raw, data, errors };
    });

    setImportRows(validated);
  };

  const handleConfirmImport = async () => {
    if (importableRows.length === 0) return;
    setImportError("");
    setImportResult(null);

    const payload = importableRows.map((r) => r.data!) as DistributorCreate[];
    let inserted = 0;
    let failed = 0;
    let firstError = "";

    for (let i = 0; i < payload.length; i += BULK_CHUNK_SIZE) {
      const chunk = payload.slice(i, i + BULK_CHUNK_SIZE);
      try {
        const created = await bulkCreateMutation.mutateAsync(chunk);
        inserted += created.length;
      } catch (err: unknown) {
        failed += chunk.length;
        if (!firstError) {
          const e = err as { response?: { data?: { detail?: string } }; message?: string };
          firstError = e?.response?.data?.detail || e?.message || "Bulk import failed";
        }
      }
    }

    setImportResult({
      inserted,
      failed,
      message: failed > 0 ? `Some rows failed: ${firstError}` : "Import complete",
    });

    if (inserted > 0 && failed === 0) {
      setImportRows([]);
      setImportHeaders([]);
      setImportFileName("");
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const [newDistributor, setNewDistributor] = useState({
    name: "",
    website_url: "",
    facebook_url: "",
    google_ads_advertiser_id: "",
    region: "",
  });
  const [editForm, setEditForm] = useState({
    name: "",
    website_url: "",
    facebook_url: "",
    instagram_url: "",
    youtube_url: "",
    google_ads_advertiser_id: "",
    region: "",
    code: "",
  });

  const handleCreate = async () => {
    const parsed = distributorCreateSchema.safeParse(newDistributor);
    if (!parsed.success) {
      alert(parsed.error.issues[0].message);
      return;
    }

    try {
      await createDistributorMutation.mutateAsync(parsed.data);
      setShowCreate(false);
      setNewDistributor({ name: "", website_url: "", facebook_url: "", google_ads_advertiser_id: "", region: "" });
    } catch (error: any) {
      console.error("Failed to create distributor:", error);
      alert(error?.response?.data?.detail || "Failed to create distributor. Please try again.");
    }
  };

  const handleStartEdit = (distributor: Distributor, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setEditingDistributor(distributor);
    setEditForm({
      name: distributor.name || "",
      website_url: distributor.website_url || "",
      facebook_url: distributor.facebook_url || "",
      instagram_url: distributor.instagram_url || "",
      youtube_url: distributor.youtube_url || "",
      google_ads_advertiser_id: distributor.google_ads_advertiser_id || "",
      region: distributor.region || "",
      code: distributor.code || "",
    });
  };

  const handleSaveEdit = async () => {
    if (!editingDistributor) return;

    const parsed = distributorUpdateSchema.safeParse(editForm);
    if (!parsed.success) {
      alert(parsed.error.issues[0].message);
      return;
    }

    try {
      await updateDistributorMutation.mutateAsync({
        id: editingDistributor.id,
        updates: parsed.data,
      });
      setEditingDistributor(null);
    } catch (error: any) {
      console.error("Failed to update distributor:", error);
      alert(error?.response?.data?.detail || "Failed to update distributor. Please try again.");
    }
  };

  const handleCancelEdit = () => {
    setEditingDistributor(null);
  };

  return (
    <div className="min-h-screen">
      <Header
        title="Distributors"
        description="Manage your dealer and distributor network"
      />

      <div className="p-8 space-y-6">
        {/* Header Actions */}
        <div className="flex justify-between items-center opacity-0 animate-fade-up">
          <div>
            <p className="text-sm text-muted-foreground font-mono">
              {distributors.length} distributor{distributors.length !== 1 ? "s" : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={() => setShowImport(true)} size="sm" variant="outline">
              <Upload className="mr-2 h-4 w-4" />
              Import CSV
            </Button>
            <Button onClick={() => setShowCreate(true)} size="sm">
              <Plus className="mr-2 h-4 w-4" />
              Add Distributor
            </Button>
          </div>
        </div>

        {/* Create Distributor Form */}
        {showCreate && (
          <Card className="border-primary/30 opacity-0 animate-fade-up">
            <CardHeader className="border-b border-border">
              <CardTitle className="text-base">Add New Distributor</CardTitle>
            </CardHeader>
            <CardContent className="pt-5 space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Distributor Name *
                  </label>
                  <Input
                    placeholder="e.g., Mustang CAT"
                    value={newDistributor.name}
                    onChange={(e) =>
                      setNewDistributor({ ...newDistributor, name: e.target.value })
                    }
                    className="mt-2"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Region
                  </label>
                  <Input
                    placeholder="e.g., Texas or Houston"
                    value={newDistributor.region}
                    onChange={(e) =>
                      setNewDistributor({ ...newDistributor, region: e.target.value })
                    }
                    className="mt-2"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Website URL
                  </label>
                  <Input
                    placeholder="https://example.com"
                    value={newDistributor.website_url}
                    onChange={(e) =>
                      setNewDistributor({ ...newDistributor, website_url: e.target.value })
                    }
                    className="mt-2"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Facebook URL
                  </label>
                  <Input
                    placeholder="https://facebook.com/page"
                    value={newDistributor.facebook_url}
                    onChange={(e) =>
                      setNewDistributor({ ...newDistributor, facebook_url: e.target.value })
                    }
                    className="mt-2"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Google Ads Advertiser ID
                  </label>
                  <Input
                    placeholder="e.g., AR12345678901234567"
                    value={newDistributor.google_ads_advertiser_id}
                    onChange={(e) =>
                      setNewDistributor({ ...newDistributor, google_ads_advertiser_id: e.target.value })
                    }
                    className="mt-2"
                  />
                </div>
              </div>
              <div className="flex gap-2 pt-2">
                <Button onClick={handleCreate} disabled={createDistributorMutation.isPending} size="sm">
                  {createDistributorMutation.isPending ? "Adding..." : "Add Distributor"}
                </Button>
                <Button variant="outline" onClick={() => setShowCreate(false)} size="sm">
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Edit Distributor Modal */}
        {editingDistributor && (
          <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-2xl border-primary/30 animate-fade-up">
              <CardHeader className="border-b border-border flex flex-row items-center justify-between">
                <CardTitle className="text-base">Edit Distributor</CardTitle>
                <Button variant="ghost" size="sm" onClick={handleCancelEdit} className="h-8 w-8 p-0">
                  <X className="h-4 w-4" />
                </Button>
              </CardHeader>
              <CardContent className="pt-5 space-y-4">
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Distributor Name *
                    </label>
                    <Input
                      placeholder="e.g., Mustang CAT"
                      value={editForm.name}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Code
                    </label>
                    <Input
                      placeholder="e.g., MCAT001"
                      value={editForm.code}
                      onChange={(e) => setEditForm({ ...editForm, code: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Region (State or City)
                    </label>
                    <Input
                      placeholder="e.g., Texas, Houston, or TX"
                      value={editForm.region}
                      onChange={(e) => setEditForm({ ...editForm, region: e.target.value })}
                      className="mt-2"
                    />
                    <p className="text-2xs text-muted-foreground mt-1">
                      Used for map location. Enter a US state name, city, or abbreviation.
                    </p>
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Website URL
                    </label>
                    <Input
                      placeholder="https://example.com"
                      value={editForm.website_url}
                      onChange={(e) => setEditForm({ ...editForm, website_url: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Facebook URL
                    </label>
                    <Input
                      placeholder="https://facebook.com/page"
                      value={editForm.facebook_url}
                      onChange={(e) => setEditForm({ ...editForm, facebook_url: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Instagram URL
                    </label>
                    <Input
                      placeholder="https://instagram.com/page"
                      value={editForm.instagram_url}
                      onChange={(e) => setEditForm({ ...editForm, instagram_url: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Google Ads Advertiser ID
                    </label>
                    <Input
                      placeholder="e.g., AR12345678901234567"
                      value={editForm.google_ads_advertiser_id}
                      onChange={(e) => setEditForm({ ...editForm, google_ads_advertiser_id: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      YouTube URL
                    </label>
                    <Input
                      placeholder="https://youtube.com/channel"
                      value={editForm.youtube_url}
                      onChange={(e) => setEditForm({ ...editForm, youtube_url: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                </div>
                <div className="flex gap-2 pt-4 border-t border-border">
                  <Button onClick={handleSaveEdit} disabled={updateDistributorMutation.isPending} size="sm">
                    {updateDistributorMutation.isPending ? "Saving..." : "Save Changes"}
                  </Button>
                  <Button variant="outline" onClick={handleCancelEdit} size="sm">
                    Cancel
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Import CSV Modal */}
        {showImport && (
          <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-4xl max-h-[90vh] flex flex-col border-primary/30 animate-fade-up">
              <CardHeader className="border-b border-border flex flex-row items-center justify-between">
                <CardTitle className="text-base flex items-center gap-2">
                  <FileSpreadsheet className="h-4 w-4" />
                  Import Distributors from CSV
                </CardTitle>
                <Button variant="ghost" size="sm" onClick={handleCloseImport} className="h-8 w-8 p-0">
                  <X className="h-4 w-4" />
                </Button>
              </CardHeader>
              <CardContent className="pt-5 space-y-4 overflow-y-auto">
                {/* Step 1: file picker */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium">1. Choose a CSV file</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        Required column: <code className="font-mono">name</code>. Optional:{" "}
                        <code className="font-mono">code, region, website_url, facebook_url,
                        instagram_url, youtube_url, google_ads_advertiser_id, status</code>.
                      </p>
                    </div>
                    <a
                      href="/distributors-template.csv"
                      download
                      className="text-xs flex items-center gap-1 text-primary hover:underline whitespace-nowrap"
                    >
                      <Download className="h-3 w-3" />
                      Download template
                    </a>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".csv,text/csv"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) void handleFilePicked(f);
                      }}
                      className="block text-xs text-muted-foreground file:mr-3 file:py-1.5 file:px-3 file:border file:border-border file:bg-secondary file:text-foreground file:text-xs file:cursor-pointer hover:file:bg-secondary/70"
                    />
                    {importFileName && (
                      <span className="text-xs text-muted-foreground font-mono truncate">
                        {importFileName}
                      </span>
                    )}
                  </div>
                </div>

                {importError && (
                  <div className="p-3 border border-destructive/30 bg-destructive/10 text-sm text-destructive flex items-start gap-2">
                    <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                    <span>{importError}</span>
                  </div>
                )}

                {/* Step 2: preview */}
                {importRows.length > 0 && (
                  <div className="space-y-3 border-t border-border pt-4">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium">2. Review</p>
                      <div className="flex items-center gap-3 text-xs">
                        <span className="text-success font-mono">{importableRows.length} ready</span>
                        {duplicateRows.length > 0 && (
                          <span className="text-amber-500 font-mono">
                            {duplicateRows.length} duplicate
                          </span>
                        )}
                        {invalidRows.length > 0 && (
                          <span className="text-destructive font-mono">
                            {invalidRows.length} invalid
                          </span>
                        )}
                        <span className="text-muted-foreground font-mono">
                          {importRows.length} total
                        </span>
                      </div>
                    </div>

                    {importHeaders.some((h) => !RECOGNIZED_HEADERS.includes(h as never)) && (
                      <p className="text-xs text-muted-foreground">
                        Unrecognized columns are ignored:{" "}
                        <span className="font-mono">
                          {importHeaders
                            .filter((h) => !RECOGNIZED_HEADERS.includes(h as never))
                            .join(", ")}
                        </span>
                      </p>
                    )}

                    <div className="border border-border max-h-[40vh] overflow-auto">
                      <table className="w-full text-xs">
                        <thead className="bg-secondary sticky top-0">
                          <tr className="text-left">
                            <th className="px-2 py-1.5 font-medium">#</th>
                            <th className="px-2 py-1.5 font-medium">Status</th>
                            <th className="px-2 py-1.5 font-medium">Name</th>
                            <th className="px-2 py-1.5 font-medium">Region</th>
                            <th className="px-2 py-1.5 font-medium">Website</th>
                            <th className="px-2 py-1.5 font-medium">Issue</th>
                          </tr>
                        </thead>
                        <tbody>
                          {importRows.map((r) => {
                            const isDup =
                              r.errors.length === 0 &&
                              r.data &&
                              existingNames.has(r.data.name.trim().toLowerCase());
                            const statusLabel =
                              r.errors.length > 0
                                ? "invalid"
                                : isDup
                                  ? "duplicate"
                                  : "ready";
                            const statusColor =
                              r.errors.length > 0
                                ? "text-destructive"
                                : isDup
                                  ? "text-amber-500"
                                  : "text-success";
                            return (
                              <tr key={r.rowNumber} className="border-t border-border">
                                <td className="px-2 py-1.5 font-mono text-muted-foreground">
                                  {r.rowNumber}
                                </td>
                                <td className={`px-2 py-1.5 font-mono ${statusColor}`}>
                                  {statusLabel}
                                </td>
                                <td className="px-2 py-1.5">
                                  {r.data?.name || r.raw.name || "—"}
                                </td>
                                <td className="px-2 py-1.5 text-muted-foreground">
                                  {r.data?.region || r.raw.region || "—"}
                                </td>
                                <td className="px-2 py-1.5 text-muted-foreground truncate max-w-[200px]">
                                  {r.data?.website_url || r.raw.website_url || "—"}
                                </td>
                                <td className="px-2 py-1.5 text-destructive">
                                  {r.errors.length > 0
                                    ? r.errors.join("; ")
                                    : isDup
                                      ? "Already exists — will be skipped"
                                      : ""}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {importResult && (
                  <div
                    className={`p-3 border text-sm flex items-start gap-2 ${
                      importResult.failed === 0
                        ? "border-success/30 bg-success/10 text-success"
                        : "border-destructive/30 bg-destructive/10 text-destructive"
                    }`}
                  >
                    {importResult.failed === 0 ? (
                      <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
                    ) : (
                      <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                    )}
                    <div>
                      <div className="font-medium">
                        {importResult.inserted} imported
                        {importResult.failed > 0 ? `, ${importResult.failed} failed` : ""}
                      </div>
                      {importResult.failed > 0 && (
                        <div className="text-xs mt-1">{importResult.message}</div>
                      )}
                    </div>
                  </div>
                )}
              </CardContent>
              <div className="flex items-center justify-between gap-2 p-4 border-t border-border">
                <p className="text-xs text-muted-foreground">
                  {importableRows.length > 0
                    ? `${importableRows.length} new distributor${
                        importableRows.length === 1 ? "" : "s"
                      } will be created.`
                    : "Pick a file to begin."}
                </p>
                <div className="flex items-center gap-2">
                  <Button variant="outline" onClick={handleCloseImport} size="sm">
                    {importResult && importResult.inserted > 0 ? "Close" : "Cancel"}
                  </Button>
                  <Button
                    onClick={handleConfirmImport}
                    disabled={importableRows.length === 0 || bulkCreateMutation.isPending}
                    size="sm"
                  >
                    {bulkCreateMutation.isPending
                      ? "Importing..."
                      : `Import ${importableRows.length} ${
                          importableRows.length === 1 ? "row" : "rows"
                        }`}
                  </Button>
                </div>
              </div>
            </Card>
          </div>
        )}

        {/* Distributors List */}
        {loading ? (
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
                <Building2 className="h-7 w-7 text-destructive" />
              </div>
              <h3 className="text-base font-medium">Failed to load distributors</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-md text-center">
                Could not connect to the server. Make sure the backend is running on port 8000.
              </p>
              <Button className="mt-6" onClick={() => refetch()} size="sm" variant="outline">
                Try Again
              </Button>
            </CardContent>
          </Card>
        ) : distributors.length === 0 ? (
          <Card className="opacity-0 animate-fade-up">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <div className="h-14 w-14 flex items-center justify-center bg-secondary border border-border mb-4">
                <Building2 className="h-7 w-7 text-muted-foreground" />
              </div>
              <h3 className="text-base font-medium">No distributors yet</h3>
              <p className="text-sm text-muted-foreground mt-1">
                Add your first distributor to start monitoring their channels
              </p>
              <Button className="mt-6" onClick={() => setShowCreate(true)} size="sm">
                <Plus className="mr-2 h-4 w-4" />
                Add Distributor
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {distributors.map((distributor: Distributor, index: number) => (
              <Link key={distributor.id} href={`/distributors/${distributor.id}`}>
                <div 
                  className="stat-card transition-all hover:border-primary/30 group cursor-pointer opacity-0 animate-fade-up"
                  style={{ animationDelay: `${index * 50}ms`, animationFillMode: 'forwards' }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div className="flex h-12 w-12 items-center justify-center bg-secondary border border-border group-hover:border-primary/30 transition-colors">
                        <Building2 className="h-5 w-5 text-primary" />
                      </div>
                      <div>
                        <div className="flex items-center gap-3">
                          <h3 className="font-medium group-hover:text-primary transition-colors">
                            {distributor.name}
                          </h3>
                          <Badge
                            className={
                              distributor.status === "active"
                                ? "border-success/30 bg-success/10 text-success"
                                : "border-border bg-secondary text-muted-foreground"
                            }
                          >
                            {distributor.status}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-4 mt-1.5 text-xs text-muted-foreground">
                          {distributor.region && (
                            <span className="flex items-center gap-1">
                              <MapPin className="h-3 w-3" />
                              {distributor.region}
                            </span>
                          )}
                          <span className="font-mono">{distributor.match_count} matches</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-6">
                      {/* Channel Icons */}
                      <div className="flex items-center gap-3">
                        {distributor.website_url && (
                          <div className="h-8 w-8 flex items-center justify-center bg-secondary border border-border">
                            <Globe className="h-4 w-4 text-muted-foreground" />
                          </div>
                        )}
                        {distributor.facebook_url && (
                          <div className="h-8 w-8 flex items-center justify-center bg-blue-500/10 border border-blue-500/20">
                            <Facebook className="h-4 w-4 text-blue-400" />
                          </div>
                        )}
                        {distributor.instagram_url && (
                          <div className="h-8 w-8 flex items-center justify-center bg-pink-500/10 border border-pink-500/20">
                            <Instagram className="h-4 w-4 text-pink-400" />
                          </div>
                        )}
                        {distributor.youtube_url && (
                          <div className="h-8 w-8 flex items-center justify-center bg-red-500/10 border border-red-500/20">
                            <Youtube className="h-4 w-4 text-red-400" />
                          </div>
                        )}
                      </div>
                      
                      {/* Edit Button */}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => handleStartEdit(distributor, e)}
                        className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      
                      <ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-all group-hover:translate-x-0.5" />
                    </div>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
