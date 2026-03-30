import { describe, it, expect } from "vitest";
import {
  campaignCreateSchema,
  distributorCreateSchema,
  scheduleCreateSchema,
  teamInviteSchema,
  orgSettingsSchema,
} from "./schemas";

describe("campaignCreateSchema", () => {
  it("accepts valid input", () => {
    const result = campaignCreateSchema.safeParse({ name: "Spring 2026" });
    expect(result.success).toBe(true);
  });

  it("rejects empty name", () => {
    const result = campaignCreateSchema.safeParse({ name: "" });
    expect(result.success).toBe(false);
  });

  it("rejects name over 100 chars", () => {
    const result = campaignCreateSchema.safeParse({ name: "x".repeat(101) });
    expect(result.success).toBe(false);
  });
});

describe("distributorCreateSchema", () => {
  it("accepts minimal input", () => {
    const result = distributorCreateSchema.safeParse({ name: "Acme Dealer" });
    expect(result.success).toBe(true);
  });

  it("rejects invalid URL", () => {
    const result = distributorCreateSchema.safeParse({
      name: "Acme",
      website_url: "not-a-url",
    });
    expect(result.success).toBe(false);
  });

  it("accepts valid google ads ID", () => {
    const result = distributorCreateSchema.safeParse({
      name: "Acme",
      google_ads_advertiser_id: "AR1234567890",
    });
    expect(result.success).toBe(true);
  });

  it("rejects invalid google ads ID", () => {
    const result = distributorCreateSchema.safeParse({
      name: "Acme",
      google_ads_advertiser_id: "INVALID",
    });
    expect(result.success).toBe(false);
  });
});

describe("scheduleCreateSchema", () => {
  it("accepts valid schedule", () => {
    const result = scheduleCreateSchema.safeParse({
      campaign_id: "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
      source: "google_ads",
      frequency: "weekly",
    });
    expect(result.success).toBe(true);
  });

  it("rejects invalid source", () => {
    const result = scheduleCreateSchema.safeParse({
      campaign_id: "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
      source: "tiktok",
      frequency: "daily",
    });
    expect(result.success).toBe(false);
  });

  it("rejects invalid frequency", () => {
    const result = scheduleCreateSchema.safeParse({
      campaign_id: "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
      source: "facebook",
      frequency: "hourly",
    });
    expect(result.success).toBe(false);
  });
});

describe("teamInviteSchema", () => {
  it("accepts valid email", () => {
    const result = teamInviteSchema.safeParse({ email: "user@example.com" });
    expect(result.success).toBe(true);
  });

  it("rejects invalid email", () => {
    const result = teamInviteSchema.safeParse({ email: "not-email" });
    expect(result.success).toBe(false);
  });
});

describe("orgSettingsSchema", () => {
  it("accepts valid hex color", () => {
    const result = orgSettingsSchema.safeParse({ report_brand_color: "#ff5500" });
    expect(result.success).toBe(true);
  });

  it("rejects invalid hex color", () => {
    const result = orgSettingsSchema.safeParse({ report_brand_color: "red" });
    expect(result.success).toBe(false);
  });
});
