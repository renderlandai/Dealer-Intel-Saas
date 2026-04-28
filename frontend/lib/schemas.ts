import { z } from "zod";

export const campaignCreateSchema = z.object({
  name: z.string().min(1, "Campaign name is required").max(100, "Name too long"),
  description: z.string().max(500, "Description too long").optional().default(""),
});

export const distributorCreateSchema = z.object({
  name: z.string().min(1, "Distributor name is required").max(100, "Name too long"),
  website_url: z.string().url("Invalid URL").or(z.literal("")).optional().default(""),
  facebook_url: z.string().url("Invalid URL").or(z.literal("")).optional().default(""),
  instagram_url: z.string().url("Invalid URL").or(z.literal("")).optional().default(""),
  google_ads_advertiser_id: z.string().regex(/^(AR\d+)?$/, "Must start with AR followed by numbers").or(z.literal("")).optional().default(""),
  region: z.string().max(100).optional().default(""),
});

export const distributorUpdateSchema = distributorCreateSchema.partial();

const optionalUrl = z
  .string()
  .trim()
  .url("Invalid URL")
  .or(z.literal(""))
  .optional()
  .default("");

export const distributorCsvRowSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(100, "Name too long"),
  code: z.string().trim().max(50, "Code too long").optional().default(""),
  website_url: optionalUrl,
  facebook_url: optionalUrl,
  instagram_url: optionalUrl,
  youtube_url: optionalUrl,
  google_ads_advertiser_id: z
    .string()
    .trim()
    .regex(/^(AR\d+)?$/, "Must start with AR followed by numbers")
    .or(z.literal(""))
    .optional()
    .default(""),
  region: z.string().trim().max(100).optional().default(""),
  status: z
    .enum(["active", "inactive"], { message: "status must be active or inactive" })
    .optional()
    .default("active"),
});

export const scheduleCreateSchema = z.object({
  campaign_id: z.string().uuid("Invalid campaign"),
  source: z.enum(["google_ads", "facebook", "instagram", "website"], { message: "Invalid scan source" }),
  frequency: z.enum(["daily", "weekly", "biweekly", "monthly"], { message: "Invalid frequency" }),
  run_at_time: z.string().regex(/^\d{2}:\d{2}$/, "Must be HH:MM format").default("09:00"),
  run_on_day: z.number().min(0).max(6).optional().nullable(),
});

export const teamInviteSchema = z.object({
  email: z.string().email("Invalid email address"),
  role: z.enum(["member", "admin"]).default("member"),
});

export const orgSettingsSchema = z.object({
  name: z.string().min(1, "Company name is required").max(100, "Name too long").optional(),
  report_brand_color: z.string().regex(/^#[0-9a-fA-F]{6}$/, "Invalid hex color").optional(),
  notify_email: z.string().email("Invalid email").or(z.literal("")).optional(),
  notify_on_violation: z.boolean().optional(),
});

export type CampaignCreateInput = z.infer<typeof campaignCreateSchema>;
export type DistributorCreateInput = z.infer<typeof distributorCreateSchema>;
export type DistributorUpdateInput = z.infer<typeof distributorUpdateSchema>;
export type DistributorCsvRowInput = z.infer<typeof distributorCsvRowSchema>;
export type ScheduleCreateInput = z.infer<typeof scheduleCreateSchema>;
export type TeamInviteInput = z.infer<typeof teamInviteSchema>;
export type OrgSettingsInput = z.infer<typeof orgSettingsSchema>;
