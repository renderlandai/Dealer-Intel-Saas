import { describe, it, expect, vi } from "vitest";

vi.mock("@supabase/supabase-js", () => ({
  createClient: vi.fn(() => ({
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
    },
  })),
}));

describe("api module", () => {
  it("exports expected functions", async () => {
    const api = await import("./api");
    expect(typeof api.getCampaigns).toBe("function");
    expect(typeof api.getDistributors).toBe("function");
    expect(typeof api.getMatches).toBe("function");
    expect(typeof api.getDashboardStats).toBe("function");
  });
});
